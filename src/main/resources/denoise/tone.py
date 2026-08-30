"""
tone.py — EQ, harmonic exciter, and loudness normalization (original
Stages 5, 6, 10).

EDIT THIS FILE IF you need to change:
  - Any EQ band's frequency range or gain (warmth, mud cut, presence,
    consonant clarity, the mumble-intelligibility boost)
  - The EQ headroom renormalization (currently: pull back down if the
    EQ stack grew the peak, never boost)
  - Harmonic exciter intensity (currently 0.05)
  - The LUFS loudness target (currently -14.0)

CROSS-MODULE DEPENDENCY: apply_harmonic_exciter() takes vad_gain as a
parameter -- this is the SAME array vad_gate.py computed and returned
earlier in the pipeline (see that file's module docstring). The exciter
uses it to avoid adding harmonic "warmth" to silence/gaps. If you call
this module's functions directly instead of through process(), you must
pass the actual vad_gain from vad_gate.apply_vad_gate(), not a
freshly-computed or approximated one -- reusing the exact same array is
what keeps the exciter's gating consistent with the VAD gate's decisions
earlier in the chain.

Order matters: EQ boosts are additive on the OUTPUT of the previous EQ
band, so they compound. The headroom renormalization step exists
specifically so tonal shaping here doesn't also silently change overall
loudness before dynamics.py's compressor/limiter (which run BEFORE this
module in the pipeline -- see main.py) have to absorb it.
"""

import numpy as np
from scipy.signal import butter, sosfilt

SAMPLE_RATE = 16000


def apply_eq(audio_data):
    """
    Stage 5: five-band EQ tuned for mumble intelligibility.
      5a. Warmth (100-300Hz), +0.30
      5b. Mud cut (320-600Hz), -0.18
      5c. Presence (2000-4000Hz), +0.35
      5d. Consonant clarity/air (4000-7500Hz), +0.15
      5e. Mumble formant boost (500-1500Hz, where vowel identity in
          mumbled speech lives), +0.28

    Stage 5f (folded into this function): the five bands above are each
    additive on the running signal, so their gains compound rather than
    sum independently -- measured on a hot pre-EQ signal, peak grew from
    0.92 to 1.07 through this stage alone. This function renormalizes
    back to the pre-EQ peak level (only pulling DOWN if the stack grew
    the peak, never boosting) so tonal shaping doesn't also change
    overall loudness. This does NOT change the balance between bands --
    it's one scalar applied equally across the whole signal after all
    five bands have summed.
    """
    pre_eq_peak = np.max(np.abs(audio_data)) + 1e-9

    sos_warmth = butter(2, [100 / (SAMPLE_RATE / 2), 300 / (SAMPLE_RATE / 2)],
                         btype='band', output='sos')
    audio_data = audio_data + 0.30 * sosfilt(sos_warmth, audio_data)

    sos_mud = butter(2, [320 / (SAMPLE_RATE / 2), 600 / (SAMPLE_RATE / 2)],
                      btype='band', output='sos')
    audio_data = audio_data - 0.18 * sosfilt(sos_mud, audio_data)

    sos_pres = butter(2, [2000 / (SAMPLE_RATE / 2), 4000 / (SAMPLE_RATE / 2)],
                       btype='band', output='sos')
    audio_data = audio_data + 0.35 * sosfilt(sos_pres, audio_data)

    sos_air = butter(2, [4000 / (SAMPLE_RATE / 2), min(7500 / (SAMPLE_RATE / 2), 0.999)],
                      btype='band', output='sos')
    audio_data = audio_data + 0.15 * sosfilt(sos_air, audio_data)

    sos_mumble = butter(2, [500 / (SAMPLE_RATE / 2), 1500 / (SAMPLE_RATE / 2)],
                         btype='band', output='sos')
    audio_data = audio_data + 0.28 * sosfilt(sos_mumble, audio_data)

    post_eq_peak = np.max(np.abs(audio_data)) + 1e-9
    if post_eq_peak > pre_eq_peak:
        audio_data = (audio_data * (pre_eq_peak / post_eq_peak)).astype(np.float32)

    return audio_data.astype(np.float32)


def apply_harmonic_exciter(audio_data, vad_gain, intensity=0.05):
    """
    Stage 6: subtle harmonic exciter for analog warmth. Scaled by
    vad_gain (computed in vad_gate.py, passed through main.py) so the
    exciter doesn't add harmonic content during silence/gaps -- only
    where the VAD gate already decided there's speech.
    """
    harmonic = (np.tanh(audio_data * 1.4) / np.tanh(1.4)).astype(np.float32)
    return (audio_data + intensity * harmonic * vad_gain).astype(np.float32)


def apply_loudness_normalization(audio_data, target_lufs=-14.0):
    """
    Stage 10: integrated LUFS loudness normalization.
    """
    import warnings
    import pyloudnorm as pyln

    # pyloudnorm requires audio length strictly greater than its block size (400ms = 6400 samples at 16kHz)
    min_loudness_samples = int(SAMPLE_RATE * 0.400)
    if len(audio_data) <= min_loudness_samples:
        print(f"PROGRESS: loudness normalization skipped, audio length ({len(audio_data)} samples) "
              f"is shorter than measurement block size ({min_loudness_samples} samples)")
        return audio_data

    loudness_meter = pyln.Meter(SAMPLE_RATE)
    try:
        integrated_loudness = loudness_meter.integrated_loudness(audio_data)
    except Exception as e:
        print(f"PROGRESS: loudness normalization skipped ({e})")
        return audio_data

    if not np.isfinite(integrated_loudness):
        print(f"PROGRESS: loudness normalization skipped, measured loudness "
              f"is not finite ({integrated_loudness}) -- input has no "
              f"meaningful energy to normalize (likely silence or fully "
              f"suppressed by earlier noise-removal stages)")
        return audio_data

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        normalized = pyln.normalize.loudness(audio_data, integrated_loudness, target_lufs)
    normalized = np.asarray(normalized, dtype=np.float32)

    if not np.all(np.isfinite(normalized)):
        bad_count = int(np.size(normalized) - np.sum(np.isfinite(normalized)))
        print(f"PROGRESS: loudness normalization produced {bad_count} "
              f"non-finite sample(s) despite a finite loudness measurement "
              f"({integrated_loudness:.2f} LUFS) -- falling back to the "
              f"pre-normalization signal rather than writing a corrupted "
              f"output")
        return audio_data

    return normalized


def apply_deesser(audio_data, threshold_db=-24.0, max_attenuation_db=6.0):
    """
    Stage 6b: dynamic de-esser. Tames piercing sibilance ('s', 'sh', 't')
    in the 5000-7500Hz band without dulling non-sibilant consonants.
    Subtracts an attenuated portion of the sibilance band only when
    high-frequency energy crosses threshold_db.
    """
    from scipy.ndimage import uniform_filter1d

    sos_sib = butter(2, [5000 / (SAMPLE_RATE / 2), min(7500 / (SAMPLE_RATE / 2), 0.999)],
                     btype='band', output='sos')
    sibilance_band = sosfilt(sos_sib, audio_data)

    window = max(1, int(SAMPLE_RATE * 0.010))  # 10ms detection window
    sib_rms = np.sqrt(uniform_filter1d(sibilance_band.astype(np.float64) ** 2, size=window) + 1e-12)

    thresh_lin = 10.0 ** (threshold_db / 20.0)
    over = sib_rms > thresh_lin

    if not np.any(over):
        return audio_data

    max_att_lin = 10.0 ** (-max_attenuation_db / 20.0)
    duck = np.ones_like(sib_rms)
    duck[over] = np.clip(thresh_lin / (sib_rms[over] + 1e-9), max_att_lin, 1.0)

    # Smooth the ducking curve (3ms attack / 25ms release)
    smooth_duck = uniform_filter1d(duck, size=max(1, int(SAMPLE_RATE * 0.015))).astype(np.float32)
    attenuated_sib = sibilance_band * (1.0 - smooth_duck)

    return (audio_data - attenuated_sib).astype(np.float32)


def process(audio_data, vad_gain):
    """Runs EQ -> harmonic exciter -> de-esser -> LUFS normalization in order.
    Requires vad_gain from vad_gate.apply_vad_gate() -- see the
    cross-module dependency note in the module docstring above."""
    audio_data = apply_eq(audio_data)
    audio_data = apply_harmonic_exciter(audio_data, vad_gain, intensity=0.05)
    audio_data = apply_deesser(audio_data)
    audio_data = apply_loudness_normalization(audio_data, target_lufs=-14.0)
    return audio_data