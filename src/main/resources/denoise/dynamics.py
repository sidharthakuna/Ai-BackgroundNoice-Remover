"""
dynamics.py — Automatic Gain Control (AGC), RMS compressor, and soft-knee limiter at 48kHz.
"""

import numpy as np
from scipy.ndimage import uniform_filter1d

SAMPLE_RATE = 48000


def apply_agc(audio, target_rms=0.12, attack_ms=80, release_ms=400,
              max_boost_db=36, min_gain=0.20, sr=SAMPLE_RATE):
    """
    Automatic Gain Control for conversational speech leveling.
    Uses a 150ms RMS window and 100Hz control envelope to eliminate volume pumping.
    """
    max_boost = 10.0 ** (max_boost_db / 20.0)
    window = max(1, int(sr * 0.150))
    rms = np.sqrt(uniform_filter1d(audio.astype(np.float32) ** 2, size=window) + 1e-12)
    raw_gain = np.clip(target_rms / rms, min_gain, max_boost)

    step = int(sr / 100)  # 10ms step
    down_gain = raw_gain[::step]
    eff_sr = sr / step
    att_a = np.exp(-1.0 / (eff_sr * attack_ms / 1000.0))
    rel_a = np.exp(-1.0 / (eff_sr * release_ms / 1000.0))

    down_smooth = np.empty_like(down_gain)
    down_smooth[0] = down_gain[0]
    for i in range(1, len(down_gain)):
        a = att_a if down_gain[i] < down_smooth[i - 1] else rel_a
        down_smooth[i] = a * down_smooth[i - 1] + (1.0 - a) * down_gain[i]

    smooth = np.interp(np.arange(len(raw_gain)), np.arange(0, len(raw_gain), step), down_smooth)
    return (audio * smooth.astype(np.float32)).astype(np.float32)


def apply_compressor(audio, threshold_db=-26, ratio=3.5, sr=SAMPLE_RATE):
    """RMS compressor acting as a gentle syllable leveler."""
    threshold_lin = 10.0 ** (threshold_db / 20.0)
    window = max(1, int(sr * 0.020))
    rms = np.sqrt(uniform_filter1d(audio.astype(np.float32) ** 2, size=window) + 1e-12)

    gain = np.ones_like(rms)
    above = rms > threshold_lin
    gain[above] = (threshold_lin + (rms[above] - threshold_lin) / ratio) / rms[above]
    gain = uniform_filter1d(gain, size=max(1, int(sr * 0.050))).astype(np.float32)
    return (audio * gain).astype(np.float32)


def apply_limiter(audio, ceiling=0.95):
    """Soft-knee limiter with tanh curve above 80% ceiling."""
    knee = 0.80 * ceiling
    sign = np.sign(audio)
    mag = np.abs(audio)
    above = mag > knee
    mag[above] = knee + (ceiling - knee) * np.tanh((mag[above] - knee) / (ceiling - knee))
    return (sign * np.minimum(mag, ceiling)).astype(np.float32)


def process(audio_data):
    """Runs AGC -> compressor -> limiter in sequence."""
    audio_data = apply_agc(audio_data)
    audio_data = apply_compressor(audio_data)
    audio_data = apply_limiter(audio_data)
    return audio_data