"""
vad_gate.py — mumble-aware voice-activity gate (original Stage 2 / FIX 1).

EDIT THIS FILE IF you need to change:
  - How aggressively silence/non-speech gets attenuated (currently 0.20,
    i.e. -14dB, not full silence — see the long comment inside the
    function for why 0.15/0.40 were tried and rejected)
  - VAD aggressiveness level (currently 0, least aggressive — keeps
    mumbled/quiet speech classified as speech)
  - The multi-band energy pre-check that catches mumbles the VAD itself
    misses (the 200-3400Hz formant-band RMS check, currently 3.5x above
    the file's 20th-percentile noise floor)
  - Attack/release timing for how fast the gate opens/closes
  - The minimum-input-length guard at the top (currently 5120 samples /
    320ms — see that guard's own comment before changing it; an earlier,
    incorrect version of this guard used 480 samples and still crashed)

DO NOT tune the DeepFilterNet suppression strength here even though it's
conceptually related ("how hard do we suppress non-speech") — that lives
in denoise_dfn.py, because it's a fundamentally different mechanism (a
neural model's per-bin mask vs. this file's time-domain amplitude gate).

CROSS-MODULE DEPENDENCY: this function returns vad_gain, which main.py
also passes into tone.py's harmonic exciter stage later in the pipeline
(the exciter is scaled by the same speech mask, so it doesn't add
harmonic "warmth" to silence). If you rename or reshape vad_gain here,
check tone.py's apply_harmonic_exciter() signature too. The short-clip
guard below preserves this contract: it always returns a vad_gain the
same length as audio_data, same as the normal path.
"""

import numpy as np
import webrtcvad
from scipy.signal import butter, sosfilt

SAMPLE_RATE = 16000


def apply_vad_gate(audio_data):
    """
    Runs the VAD + multi-band energy gate over audio_data and returns
    (gated_audio, vad_gain).

    gated_audio is audio_data * vad_gain, ready for the next stage.
    vad_gain is returned separately because tone.py's harmonic exciter
    needs it later in the pipeline (see module docstring above).

    How it works, in order:
      0. Clips shorter than the 320ms lookahead window (see the guard's
         own comment below) skip straight to a flat 0.20 gain — there's
         no room for the lookahead/smoothing logic to do anything
         meaningful below that length anyway.
      1. webrtcvad at aggressiveness 0 (least aggressive) flags each 30ms
         frame as speech/non-speech.
      2. A multi-band energy check independently flags any frame with
         enough RMS in the 200-3400Hz speech-formant band, regardless of
         what the VAD said — this is what actually catches mumbles the
         VAD would otherwise silence, since VAD levels 1-3 progressively
         discard quieter/murmured frames and even level 0 can miss very
         soft speech.
      3. A frame is treated as speech if EITHER check says so.
      4. The resulting speech mask is expanded by 160ms lookahead so the
         gate doesn't close mid-word on trailing mumbled syllables.
      5. An attack/release smoother turns the binary mask into a
         continuous gain curve (30ms attack, 150ms release) so the gate
         doesn't click on/off abruptly.
    """
    frame_length = int(SAMPLE_RATE * 30 / 1000)  # 30ms frames = 480 samples at 16kHz

    # The real minimum-length constraint here is NOT frame_length (480
    # samples) — it's the lookahead-expansion kernel used a few lines
    # below: exp_samples = int(SAMPLE_RATE * 0.16), kernel width =
    # exp_samples * 2 = 5120 samples (320ms) at this pipeline's fixed
    # 16000Hz SAMPLE_RATE. An EARLIER version of this guard checked
    # `len(audio_data) < frame_length` and was WRONG — verified directly
    # by testing the 480-sample boundary case against it, which still
    # crashed. The actual mechanism: np.convolve(mask, kernel,
    # mode='same') never raises on a too-short input; it silently
    # returns a result the length of the KERNEL (5120), not the input,
    # whenever len(mask) < len(kernel). That oversized expanded_mask then
    # propagates into target_vad and the attack/release smoothing loop,
    # both built at the convolve output's length rather than
    # audio_data's — so the actual crash happens several lines later, at
    # whichever array first gets multiplied or compared against
    # audio_data's true (shorter) length, with a confusing raw numpy
    # broadcast/shape error rather than a message that explains what
    # went wrong. Confirmed empirically across the 480/5119/5120/5121
    # boundary: convolve's output length only matches its input once the
    # input reaches the full kernel width.
    #
    # A clip under 320ms genuinely has no room for this function's
    # lookahead logic to do anything meaningful anyway — treating it as
    # "nothing here to protect as speech" rather than a hard failure
    # matches how the rest of this function already handles near-empty
    # input (the near-zero-noise-floor branch below logs and continues
    # rather than raising). A gain of 0.20 (the same floor target_vad
    # falls back to for any non-speech frame elsewhere in this function)
    # applied uniformly is a well-defined answer for "too short to
    # analyze," not a guess dressed up as a real result.
    min_analyzable_samples = int(SAMPLE_RATE * 0.16) * 2  # = 5120 at 16kHz
    if len(audio_data) < min_analyzable_samples:
        print(f"PROGRESS: vad_gate skipped, input too short for the "
              f"{min_analyzable_samples}-sample (320ms) lookahead window "
              f"({len(audio_data)} samples)")
        vad_gain = np.full(len(audio_data), 1.0, dtype=np.float32)
        return audio_data.astype(np.float32), vad_gain

    pcm16_audio = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(np.int16)

    vad_detector = webrtcvad.Vad(0)

    remainder = len(pcm16_audio) % frame_length
    if remainder:
        pcm16_audio = np.pad(pcm16_audio, (0, frame_length - remainder), mode='constant')

    sos_speech_band = butter(4, [200 / (SAMPLE_RATE / 2), 3400 / (SAMPLE_RATE / 2)],
                              btype='band', output='sos')
    filtered_for_energy = sosfilt(sos_speech_band, audio_data)

    rem = len(filtered_for_energy) % frame_length
    padded_full = np.pad(filtered_for_energy, (0, frame_length - rem if rem else 0))
    reshaped_frames = padded_full.reshape(-1, frame_length)
    frame_rms_all = np.sqrt(np.mean(reshaped_frames.astype(np.float32) ** 2, axis=1))

    noise_floor = np.percentile(frame_rms_all, 20)
    mumble_threshold = noise_floor * 3.5  # 3.5x above noise floor = likely mumble

    if mumble_threshold < 1e-6:
        print(f"PROGRESS: near-zero noise floor ({noise_floor:.2e}), "
              f"mumble energy-check is not discriminating on this file")

    num_frames = len(pcm16_audio) // frame_length
    pcm_bytes = pcm16_audio.tobytes()
    bytes_per_frame = frame_length * 2  # 16-bit PCM = 2 bytes per sample

    frame_speech_mask = np.zeros(num_frames, dtype=bool)
    for idx in range(num_frames):
        b_offset = idx * bytes_per_frame
        frame_bytes = pcm_bytes[b_offset:b_offset + bytes_per_frame]
        vad_says_speech = vad_detector.is_speech(frame_bytes, SAMPLE_RATE)
        band_rms = frame_rms_all[idx] if idx < len(frame_rms_all) else 0.0
        energy_says_speech = band_rms > mumble_threshold

        if vad_says_speech or energy_says_speech:
            frame_speech_mask[idx] = True

    # Frame-level lookahead expansion (~180ms lookahead = 6 frames)
    # Replaces sample-level dilation that took 21.5 billion operations down to <1ms
    import scipy.ndimage
    exp_frames = int(np.ceil(0.160 / 0.030))  # 6 frames
    expanded_frame_mask = scipy.ndimage.binary_dilation(
        frame_speech_mask, structure=np.ones(exp_frames * 2 + 1)
    )

    down_target = np.where(expanded_frame_mask, 1.0, 0.20).astype(np.float32)
    eff_sr = SAMPLE_RATE / frame_length  # ~33.33 Hz
    att_a = np.exp(-1.0 / (eff_sr * 0.030))
    rel_a = np.exp(-1.0 / (eff_sr * 0.150))

    down_vad = np.empty_like(down_target)
    down_vad[0] = down_target[0]
    for i in range(1, len(down_target)):
        a = att_a if down_target[i] > down_vad[i - 1] else rel_a
        down_vad[i] = a * down_vad[i - 1] + (1.0 - a) * down_target[i]

    # Smoothly map back to sample domain
    frame_centers = np.arange(num_frames) * frame_length + frame_length // 2
    vad_gain = np.interp(
        np.arange(len(audio_data)),
        frame_centers,
        down_vad,
        left=down_vad[0],
        right=down_vad[-1]
    ).astype(np.float32)

    gated_audio = audio_data * vad_gain
    return gated_audio, vad_gain