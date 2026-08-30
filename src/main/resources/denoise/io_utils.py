"""
io_utils.py — audio loading, stereo channel splitting, and file output.

EDIT THIS FILE IF you need to change:
  - How input files are validated (missing file, empty file, unsupported codec)
  - The real-stereo vs. mono-in-stereo-container detection (the 0.98
    correlation threshold — FIX 6 in the original monolithic script)
  - The side-channel attenuation factor (currently 0.15)
  - How the final mono/stereo output gets written to disk

DO NOT put any DSP processing logic here (no EQ, no gain staging, no
filtering). This file's only job is "bytes in -> numpy arrays out" and
"numpy arrays in -> bytes out." If you're tuning a filter, threshold, or
gain stage, you want a different file — see the package README.
"""

import os
import numpy as np
import librosa
import soundfile as sf

SAMPLE_RATE = 16000


def validate_input_path(input_path):
    """
    Raises a plain Exception (caught by main.py's error wrapper) with a
    user-facing message if the input file is missing or empty. Kept as a
    raise-not-print here so this module stays independently testable —
    main.py is the only place that prints the "ERROR:" line the Java layer
    parses.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"input file not found: {input_path}")
    if os.path.getsize(input_path) == 0:
        raise ValueError("input file is empty")


def load_and_split_channels(input_path):
    """
    Loads the input file and determines whether it's genuinely stereo,
    mono wearing a stereo container (duplicated channels from an upstream
    transcode, e.g. WhatsApp's mono Opus voice notes re-wrapped as WAV),
    or plain mono.

    Returns a dict with:
      audio_data              — the single channel to run through the DSP
                                 chain (mid channel for real stereo, the
                                 averaged channel for mono-in-container,
                                 the raw signal for plain mono)
      side_channel             — None, or the attenuated (L-R)/2 side
                                 channel, ONLY when source_is_real_stereo
      is_stereo                — bool, whether the input had 2 channels
      source_is_real_stereo    — bool, whether those 2 channels carried
                                 genuine stereo information (vs. dither)

    Threshold note (FIX 6 from the original script): channel correlation
    > 0.98 is treated as "this is decode dither duplicated to 2 channels,
    not real stereo." Genuine stereo speech (two mics, room ambience)
    essentially never exceeds ~0.95 correlation even with a centered
    speaker, because independent mic self-noise and room reflections put
    a ceiling on how correlated two real channels can be. If you're
    seeing real stereo recordings getting misclassified as mono, this is
    the number to revisit -- but see the file's original comment history
    before changing it; it was set from a measured real sample (L/R
    correlation 0.997, side-channel RMS ~22dB below main signal).
    """
    try:
        raw_audio, sr = sf.read(input_path, dtype="float32", always_2d=False)

        if raw_audio.ndim == 2:
            raw_audio = raw_audio.T
        if sr != SAMPLE_RATE:
            raw_audio = librosa.resample(raw_audio, orig_sr=sr, target_sr=SAMPLE_RATE)
    except Exception:
        raw_audio, _ = librosa.load(input_path, sr=SAMPLE_RATE, mono=False)

    raw_audio = np.nan_to_num(raw_audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    # Handle multi-channel (>2 channels, e.g. 5.1 surround) by downmixing to stereo
    if raw_audio.ndim == 2 and raw_audio.shape[0] > 2:
        num_ch = raw_audio.shape[0]
        if num_ch == 6:  # 5.1 layout: L, R, C, LFE, Ls, Rs
            left = raw_audio[0] + 0.7071 * raw_audio[2] + 0.7071 * raw_audio[4]
            right = raw_audio[1] + 0.7071 * raw_audio[2] + 0.7071 * raw_audio[5]
            raw_audio = np.stack([left, right])
        else:
            mid = np.mean(raw_audio, axis=0)
            raw_audio = np.stack([mid, mid])

    is_stereo = raw_audio.ndim == 2 and raw_audio.shape[0] == 2

    if is_stereo:
        left_channel = raw_audio[0]
        right_channel = raw_audio[1]
        std_l = float(np.std(left_channel))
        std_r = float(np.std(right_channel))
        if std_l > 1e-6 and std_r > 1e-6:
            cov = np.corrcoef(left_channel, right_channel)
            channel_correlation = float(cov[0, 1]) if cov.ndim == 2 else 1.0
            source_is_real_stereo = bool(np.isfinite(channel_correlation) and channel_correlation < 0.98)
        else:
            source_is_real_stereo = False
    else:
        source_is_real_stereo = False

    if is_stereo and source_is_real_stereo:
        mid_channel = ((left_channel + right_channel) / 2).astype(np.float32)
        side_channel = ((left_channel - right_channel) / 2).astype(np.float32)
        side_channel = side_channel * 0.15
        audio_data = mid_channel
    elif is_stereo:
        # Mono-in-stereo-container: average once, skip mid/side entirely.
        audio_data = ((left_channel + right_channel) / 2).astype(np.float32)
        side_channel = None
    else:
        audio_data = (raw_audio[0] if raw_audio.ndim == 2 else raw_audio).astype(np.float32)
        side_channel = None

    return {
        "audio_data": audio_data,
        "side_channel": side_channel,
        "is_stereo": is_stereo,
        "source_is_real_stereo": source_is_real_stereo,
    }


def reconstruct_output(audio_data, side_channel, is_stereo, source_is_real_stereo):
    """
    Takes the fully-processed mono audio_data and produces the final array
    to write to disk: either (n, 2) stereo or (n,) mono.
    """

    if is_stereo and source_is_real_stereo:
        length_diff = abs(len(audio_data) - len(side_channel))
        if length_diff > 0:
            print(f"PROGRESS: stereo length mismatch, audio_data={len(audio_data)} "
                  f"side_channel={len(side_channel)} diff={length_diff}")
        n = min(len(audio_data), len(side_channel))
        audio_data = audio_data[:n]
        side_channel = side_channel[:n]

        L = (audio_data + side_channel).astype(np.float32)
        R = (audio_data - side_channel).astype(np.float32)
        peak = np.max(np.abs(np.stack([L, R]))) + 1e-9
        if peak > 0.95:
            L = (L / peak * 0.95).astype(np.float32)
            R = (R / peak * 0.95).astype(np.float32)
        return np.stack([L, R], axis=1)

    elif is_stereo:
        peak = np.max(np.abs(audio_data)) + 1e-9
        if peak > 0.95:
            audio_data = audio_data / peak * 0.95
        return np.stack([audio_data, audio_data], axis=1)

    else:
        # Stage 8's limiter (in dynamics.py) guarantees a 0.95 peak
        # ceiling, but LUFS normalization (tone.py, applied after) can
        # apply enough positive gain to push the peak back past that
        # ceiling on quiet, high-crest-factor audio (e.g. mumbled speech
        # with sharp consonants). Re-enforce the same 0.95 ceiling here
        # instead of relying on the hard np.clip in save_output().
        peak = np.max(np.abs(audio_data)) + 1e-9
        if peak > 0.95:
            audio_data = audio_data / peak * 0.95
        return audio_data


def save_output(output_path, final_output, is_stereo):
    final_output = np.clip(final_output, -1.0, 1.0)
    sf.write(output_path, final_output, SAMPLE_RATE)
    print(f"PROGRESS: done stereo={is_stereo}")