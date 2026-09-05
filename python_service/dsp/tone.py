"""
tone.py — 5-Band Studio Voice Parametric EQ, Dynamic De-Esser & ITU-R BS.1770-4 Loudness Normalization.
Shapes natural vocal warmth and presence, controls sibilants, and normalizes to standard broadcast LUFS.
"""

import numpy as np
import scipy.signal
import scipy.ndimage
from scipy.signal import butter, sosfiltfilt
from python_service.config import SAMPLE_RATE


def apply_tone_mastering(audio: np.ndarray, target_lufs: float = -14.0) -> np.ndarray:
    """
    Studio Tone Mastering Pipeline:
    1. 5-Band Parametric EQ (160Hz warmth, 420Hz boxiness cut, 1kHz clarity, 3.2kHz presence, 8.5kHz air).
    2. Dynamic De-Esser (5500Hz - 8500Hz) to reduce piercing 's' sounds.
    3. ITU-R BS.1770-4 / EBU R128 Loudness Normalization with true-peak limiter guard.
    """
    if len(audio) < 1000:
        return audio.astype(np.float32)

    # 1. 5-Band Parametric EQ
    def peaking_eq(x: np.ndarray, f0: float, gain_db: float, q: float) -> np.ndarray:
        w0 = 2.0 * np.pi * f0 / SAMPLE_RATE
        A = 10.0 ** (gain_db / 40.0)
        alpha = np.sin(w0) / (2.0 * q)
        b0 = 1.0 + alpha * A
        b1 = -2.0 * np.cos(w0)
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * np.cos(w0)
        a2 = 1.0 - alpha / A
        b = np.array([b0, b1, b2]) / a0
        a = np.array([a0, a1, a2]) / a0
        return scipy.signal.lfilter(b, a, x).astype(np.float32)

    eq_audio = peaking_eq(audio, 160.0, 1.2, 1.0)     # Warmth shelf
    eq_audio = peaking_eq(eq_audio, 420.0, -1.8, 1.2) # Boxiness / mud cut
    eq_audio = peaking_eq(eq_audio, 1000.0, 1.0, 1.0) # Vocal formant clarity
    eq_audio = peaking_eq(eq_audio, 3200.0, 2.0, 1.2) # Intelligibility & presence
    eq_audio = peaking_eq(eq_audio, 8500.0, 1.5, 0.8) # High-end air

    # 2. Dynamic De-Esser (5500Hz - 8500Hz)
    sos_sibilance = butter(2, [5500.0 / (SAMPLE_RATE / 2), 8500.0 / (SAMPLE_RATE / 2)], btype="bandpass", output="sos")
    sibilance = sosfiltfilt(sos_sibilance, eq_audio)
    sibilance_env = scipy.ndimage.gaussian_filter1d(np.abs(sibilance), sigma=SAMPLE_RATE * 0.005)

    sibilance_thresh = 0.08
    over_thresh = sibilance_env > sibilance_thresh
    deess_gain = np.ones_like(eq_audio)
    if np.any(over_thresh):
        deess_gain[over_thresh] = 1.0 - 0.4 * (sibilance_env[over_thresh] - sibilance_thresh) / (sibilance_env[over_thresh] + 1e-6)
        deess_gain = np.clip(deess_gain, 0.5, 1.0)

    deessed = (eq_audio * deess_gain).astype(np.float32)

    # 3. ITU-R BS.1770-4 / EBU R128 Normalization
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(SAMPLE_RATE)
        loudness = meter.integrated_loudness(deessed)
        if not np.isneginf(loudness) and not np.isnan(loudness):
            deessed = pyln.normalize.loudness(deessed, loudness, target_lufs).astype(np.float32)
    except Exception:
        # Fallback RMS normalization if pyloudnorm unavailable
        rms = np.sqrt(np.mean(deessed ** 2) + 1e-9)
        target_rms = 10.0 ** (-16.0 / 20.0)
        gain = np.clip(target_rms / rms, 0.1, 4.0)
        deessed = deessed * gain

    # True-peak guard
    peak = np.max(np.abs(deessed)) + 1e-9
    if peak > 0.95:
        deessed = (deessed / peak) * 0.95

    return deessed.astype(np.float32)
