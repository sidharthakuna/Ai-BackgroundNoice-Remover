"""
tone.py — 5-band mastering EQ, harmonic exciter, dynamic de-esser, and LUFS normalization at 48kHz.
"""

import warnings
import numpy as np
from scipy.signal import butter, sosfilt
from scipy.ndimage import uniform_filter1d
import pyloudnorm as pyln

SAMPLE_RATE = 48000


def apply_eq(audio_data):
    """
    5-band voice mastering EQ at 48kHz:
      1. Warmth (100-300Hz), +0.30
      2. Mud cut (320-600Hz), -0.18
      3. Presence (2000-4000Hz), +0.35
      4. Consonant clarity/air (4000-12000Hz), +0.20 (full studio presence)
      5. Mumble formant boost (500-1500Hz), +0.28
    Includes headroom renormalization to avoid digital clipping.
    """
    pre_eq_peak = float(np.max(np.abs(audio_data))) + 1e-9
    nyq = SAMPLE_RATE / 2.0

    sos_warmth = butter(2, [100 / nyq, 300 / nyq], btype="band", output="sos")
    audio_data = audio_data + 0.30 * sosfilt(sos_warmth, audio_data)

    sos_mud = butter(2, [320 / nyq, 600 / nyq], btype="band", output="sos")
    audio_data = audio_data - 0.18 * sosfilt(sos_mud, audio_data)

    sos_pres = butter(2, [2000 / nyq, 4000 / nyq], btype="band", output="sos")
    audio_data = audio_data + 0.35 * sosfilt(sos_pres, audio_data)

    sos_air = butter(2, [4000 / nyq, min(12000 / nyq, 0.99)], btype="band", output="sos")
    audio_data = audio_data + 0.20 * sosfilt(sos_air, audio_data)

    sos_mumble = butter(2, [500 / nyq, 1500 / nyq], btype="band", output="sos")
    audio_data = audio_data + 0.28 * sosfilt(sos_mumble, audio_data)

    post_eq_peak = float(np.max(np.abs(audio_data))) + 1e-9
    if post_eq_peak > pre_eq_peak:
        audio_data = (audio_data * (pre_eq_peak / post_eq_peak)).astype(np.float32)

    return audio_data.astype(np.float32)


def apply_harmonic_exciter(audio_data, vad_gain, intensity=0.05):
    """Subtle analog saturation exciter scaled by vad_gain to only enhance vocal parts."""
    harmonic = (np.tanh(audio_data * 1.4) / np.tanh(1.4)).astype(np.float32)
    return (audio_data + intensity * harmonic * vad_gain).astype(np.float32)


def apply_deesser(audio_data, threshold_db=-24.0, max_attenuation_db=6.0):
    """Dynamic de-esser taming harsh 's', 'sh', 't' sibilance in the 5000-9000Hz band."""
    nyq = SAMPLE_RATE / 2.0
    sos_sib = butter(2, [5000 / nyq, min(9000 / nyq, 0.99)], btype="band", output="sos")
    sibilance_band = sosfilt(sos_sib, audio_data)

    window = max(1, int(SAMPLE_RATE * 0.010))  # 10ms detection window
    sib_rms = np.sqrt(uniform_filter1d(sibilance_band.astype(np.float32) ** 2, size=window) + 1e-12)

    thresh_lin = 10.0 ** (threshold_db / 20.0)
    over = sib_rms > thresh_lin

    if not np.any(over):
        return audio_data

    max_att_lin = 10.0 ** (-max_attenuation_db / 20.0)
    duck = np.ones_like(sib_rms)
    duck[over] = np.clip(thresh_lin / (sib_rms[over] + 1e-9), max_att_lin, 1.0)

    smooth_duck = uniform_filter1d(duck, size=max(1, int(SAMPLE_RATE * 0.015))).astype(np.float32)
    attenuated_sib = sibilance_band * (1.0 - smooth_duck)

    return (audio_data - attenuated_sib).astype(np.float32)


def apply_loudness_normalization(audio_data, target_lufs=-14.0):
    """Normalizes integrated loudness to EBU R128 / ITU-R BS.1770 standard (-14 LUFS)."""
    min_loudness_samples = int(SAMPLE_RATE * 0.400)
    if len(audio_data) <= min_loudness_samples:
        return audio_data

    loudness_meter = pyln.Meter(SAMPLE_RATE)
    try:
        integrated_loudness = loudness_meter.integrated_loudness(audio_data)
    except Exception:
        return audio_data

    if not np.isfinite(integrated_loudness):
        return audio_data

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        normalized = pyln.normalize.loudness(audio_data, integrated_loudness, target_lufs)

    normalized = np.asarray(normalized, dtype=np.float32)
    if not np.all(np.isfinite(normalized)):
        return audio_data

    return normalized


def process(audio_data, vad_gain):
    """Runs EQ -> harmonic exciter -> de-esser -> LUFS normalization in order."""
    audio_data = apply_eq(audio_data)
    audio_data = apply_harmonic_exciter(audio_data, vad_gain, intensity=0.05)
    audio_data = apply_deesser(audio_data)
    audio_data = apply_loudness_normalization(audio_data, target_lufs=-14.0)
    return audio_data