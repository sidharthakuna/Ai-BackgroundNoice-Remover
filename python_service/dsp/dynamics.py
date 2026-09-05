"""
dynamics.py — Broadcast dynamics processing:
1. Fast AGC speech leveling for fluctuating microphone distance.
2. Broadcast RMS compressor (-26dB threshold, 3.5:1 ratio, 20ms attack, 200ms release).
3. Soft-knee peak limiter with tanh saturation to prevent digital clipping.
"""

import numpy as np
import scipy.ndimage
from python_service.config import SAMPLE_RATE


def apply_dynamics(audio: np.ndarray, comp_ratio: float = 3.5, target_peak: float = 0.92) -> np.ndarray:
    """
    Broadcast Dynamics Processing:
    - Leveler balances quiet/loud phrases without pumping.
    - Compressor gently tightens dynamic range.
    - Soft-knee limiter protects output from clipping.
    """
    if len(audio) < 1000:
        return audio.astype(np.float32)

    # Step 1: RMS AGC Speech Leveler
    window_samples = int(0.150 * SAMPLE_RATE)
    hop_samples = int(0.010 * SAMPLE_RATE)
    num_frames = (len(audio) - window_samples) // hop_samples

    if num_frames > 10:
        frames = np.lib.stride_tricks.sliding_window_view(audio[:num_frames * hop_samples + window_samples], window_samples)[::hop_samples]
        frame_rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-9)

        # Target speech RMS ~ -20 dBFS (~0.10)
        target_rms = 0.10
        raw_gain = np.clip(target_rms / frame_rms, 0.4, 2.5)

        # Smooth gain curve
        smooth_gain = scipy.ndimage.gaussian_filter1d(raw_gain, sigma=15.0)
        gain_curve = np.interp(np.arange(len(audio)), np.arange(len(smooth_gain)) * hop_samples, smooth_gain)
        leveled = (audio * gain_curve).astype(np.float32)
    else:
        leveled = audio

    # Step 2: RMS Compressor
    threshold_linear = 10.0 ** (-26.0 / 20.0)  # ~0.05
    env_decay = np.exp(-1.0 / (0.200 * SAMPLE_RATE))
    env_attack = np.exp(-1.0 / (0.020 * SAMPLE_RATE))

    envelope = 0.0
    compressed = np.zeros_like(leveled)
    for i, x in enumerate(leveled):
        abs_x = abs(x)
        if abs_x > envelope:
            envelope = env_attack * envelope + (1.0 - env_attack) * abs_x
        else:
            envelope = env_decay * envelope + (1.0 - env_decay) * abs_x

        if envelope > threshold_linear:
            gain = (envelope / threshold_linear) ** (1.0 / comp_ratio - 1.0)
        else:
            gain = 1.0
        compressed[i] = x * gain

    # Step 3: Soft-Knee Limiter (tanh saturation above 0.80)
    knee_start = 0.80
    over_knee = np.abs(compressed) > knee_start
    if np.any(over_knee):
        sign = np.sign(compressed)
        mag = np.abs(compressed)
        mag[over_knee] = knee_start + (1.0 - knee_start) * np.tanh((mag[over_knee] - knee_start) / (1.0 - knee_start))
        compressed = sign * mag

    peak = np.max(np.abs(compressed)) + 1e-9
    if peak > target_peak:
        compressed = (compressed / peak) * target_peak

    return compressed.astype(np.float32)
