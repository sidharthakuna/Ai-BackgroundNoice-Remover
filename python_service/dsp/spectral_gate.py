"""
spectral_gate.py — Wiener-style multi-band spectral gating.
Uses Hann window STFT and 3-frame temporal smoothing across the time axis
to eliminate chirping and musical artifact fluttering.
"""

import gc
import numpy as np
import scipy.ndimage
from scipy.signal import stft, istft
from python_service.config import SAMPLE_RATE


def apply_spectral_gating(signal: np.ndarray, over_subtract: float = 1.8, floor: float = 0.08,
                          n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """
    Wiener-style smoothed multi-band STFT spectral gating.
    Applies 3-frame temporal smoothing to gain masks to eliminate musical noise.
    """
    if len(signal) < n_fft:
        return signal.astype(np.float32)

    _, _, Zxx = stft(signal, fs=SAMPLE_RATE, window="hann", nperseg=n_fft, noverlap=n_fft - hop)
    mag = np.abs(Zxx)
    phase = np.angle(Zxx)
    del Zxx

    frame_energy = np.sum(mag ** 2, axis=0)
    noise_thresh = np.percentile(frame_energy, 15)
    noise_frames = mag[:, frame_energy <= noise_thresh]
    if noise_frames.shape[1] == 0:
        noise_frames = mag[:, :max(1, int(mag.shape[1] * 0.15))]

    noise_spectrum = np.mean(noise_frames, axis=1, keepdims=True)
    del noise_frames, frame_energy

    # Wiener gain mask formulation
    snr_est = np.maximum(mag / (noise_spectrum + 1e-9) - 1.0, 0.0)
    gain_mask = snr_est / (snr_est + over_subtract)
    gain_mask = np.maximum(gain_mask, floor)

    # 3-frame temporal smoothing across time prevents musical tone flutter
    smooth_gain = scipy.ndimage.uniform_filter1d(gain_mask, size=3, axis=1)

    cleaned_mag = mag * smooth_gain
    del mag, noise_spectrum, snr_est, gain_mask, smooth_gain

    D_clean = cleaned_mag * np.exp(1j * phase)
    del cleaned_mag, phase

    _, result = istft(D_clean, fs=SAMPLE_RATE, window="hann", nperseg=n_fft, noverlap=n_fft - hop)
    del D_clean

    gc.collect()
    return result[:len(signal)].astype(np.float32)
