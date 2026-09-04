"""
denoise_dfn.py — Rumble filtering, Wiener spectral gating, and native 48kHz DeepFilterNet3 neural enhancement.
"""

import os
import sys
import types
from dataclasses import dataclass
import numpy as np
import torch
from scipy.signal import butter, sosfiltfilt, stft, istft
import scipy.ndimage

# Prevent CPU thrashing on container CFS CPU quotas
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["TORCH_NUM_THREADS"] = "1"

# Compatibility shim for DeepFilterNet on newer torchaudio versions (2.1+ / 2.12+)
if "torchaudio.backend" not in sys.modules:
    try:
        @dataclass
        class AudioMetaData:
            sample_rate: int = 48000
            num_frames: int = 0
            num_channels: int = 1
            bits_per_sample: int = 16
            encoding: str = "PCM_S"

        backend_mod = types.ModuleType("torchaudio.backend")
        common_mod = types.ModuleType("torchaudio.backend.common")
        common_mod.AudioMetaData = getattr(sys.modules.get("torchaudio", None), "AudioMetaData", AudioMetaData)
        backend_mod.common = common_mod
        sys.modules["torchaudio.backend"] = backend_mod
        sys.modules["torchaudio.backend.common"] = common_mod
        if "torchaudio" in sys.modules:
            sys.modules["torchaudio"].backend = backend_mod
    except Exception:
        pass

torch.set_num_threads(1)
torch.set_grad_enabled(False)

SAMPLE_RATE = 48000


def apply_highpass(audio_data, cutoff_hz=70.0):
    """Stage 1: removes low-end sub-bass rumble below cutoff_hz using a 4th-order Butterworth SOS filter."""
    sos = butter(4, cutoff_hz / (SAMPLE_RATE / 2), btype="high", output="sos")
    return sosfiltfilt(sos, audio_data).astype(np.float32)


def apply_lowpass(audio_data, cutoff_hz=20000):
    """Optional ceiling filter."""
    sos = butter(4, cutoff_hz / (SAMPLE_RATE / 2), btype="low", output="sos")
    return sosfiltfilt(sos, audio_data).astype(np.float32)


def spectral_subtract(signal, over_subtract=1.8, floor=0.08, n_fft=2048, hop=512):
    """
    Stage 1.5: Wiener-style smoothed multi-band STFT spectral gating.
    Uses 3-frame temporal smoothing to eliminate musical noise / chirping artifacts.
    """
    if len(signal) < n_fft:
        print(f"PROGRESS: spectral_subtract skipped, input too short ({len(signal)} samples)", flush=True)
        return signal

    f, t_axis, Zxx = stft(signal, fs=SAMPLE_RATE, window="hann", nperseg=n_fft, noverlap=n_fft - hop)
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

    # 3-frame temporal smoothing across time axis prevents isolated musical warbles
    smooth_gain = scipy.ndimage.uniform_filter1d(gain_mask, size=3, axis=1)

    cleaned_mag = mag * smooth_gain
    del mag, noise_spectrum, snr_est, gain_mask, smooth_gain

    D_clean = cleaned_mag * np.exp(1j * phase)
    del cleaned_mag, phase

    _, result = istft(D_clean, fs=SAMPLE_RATE, window="hann", nperseg=n_fft, noverlap=n_fft - hop)
    del D_clean

    import gc
    gc.collect()
    return result[:len(signal)].astype(np.float32)


_CACHED_DF_MODEL = None
_CACHED_DF_STATE = None
_CACHED_DF_POSTFILTER = None


def apply_deepfilternet(audio_data, atten_lim_db=30, post_filter=False):
    """
    Stage 3: DeepFilterNet neural denoiser running directly at native 48kHz.
    Runs with torch.inference_mode() and single-thread execution.
    """
    global _CACHED_DF_MODEL, _CACHED_DF_STATE, _CACHED_DF_POSTFILTER
    try:
        from df.enhance import enhance, init_df
    except ImportError as e:
        print(f"PROGRESS: DeepFilterNet neural denoiser not available ({e}), bypassing neural stage", flush=True)
        return audio_data

    try:
        if _CACHED_DF_MODEL is None or _CACHED_DF_STATE is None or _CACHED_DF_POSTFILTER != post_filter:
            _CACHED_DF_MODEL, _CACHED_DF_STATE, _ = init_df(post_filter=post_filter)
            _CACHED_DF_POSTFILTER = post_filter

        audio_tensor = torch.from_numpy(audio_data[np.newaxis, :]).float()
        with torch.inference_mode():
            result = enhance(
                _CACHED_DF_MODEL,
                _CACHED_DF_STATE,
                audio_tensor,
                atten_lim_db=atten_lim_db
            ).squeeze().cpu().numpy().astype(np.float32)

        del audio_tensor

        # Match exact length
        n = len(audio_data)
        if len(result) < n:
            result = np.pad(result, (0, n - len(result)))
        elif len(result) > n:
            result = result[:n]

        import gc
        gc.collect()
        return result.astype(np.float32)

    except Exception as exc:
        print(f"PROGRESS: DeepFilterNet processing fallback ({exc})", flush=True)
        return audio_data


MODE_SETTINGS = {
    "gentle": {"over_subtract": 1.2, "floor": 0.10, "atten_lim_db": 18, "post_filter": False},
    "balanced": {"over_subtract": 1.8, "floor": 0.08, "atten_lim_db": 30, "post_filter": False},
    "aggressive": {"over_subtract": 2.5, "floor": 0.04, "atten_lim_db": 36, "post_filter": True},
}