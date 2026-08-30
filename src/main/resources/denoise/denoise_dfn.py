"""
denoise_dfn.py — the actual noise-removal stages (original Stages 1, 1.5, 3).

Three sub-stages, run in order by process():
  1. High-pass filter — removes rumble below 80Hz.
  2. Spectral subtraction — STFT-domain noise-profile subtraction.
  3. DeepFilterNet (DFN) — the neural denoiser doing the heavy lifting.

Also present, but NOT yet part of process() — apply_lowpass(), a fixed
ceiling above 7500Hz by default. See that function's own docstring for
why it's opt-in rather than wired into the default pipeline, and why
its cutoff can't go as high as 8000Hz at this pipeline's sample rate.

EDIT THIS FILE IF you need to change:
  - The high-pass cutoff frequency (currently 80Hz)
  - The low-pass cutoff frequency, if/when you wire apply_lowpass() in
    (currently 7500Hz — MUST stay below 8000Hz, the Nyquist frequency
    at this pipeline's fixed 16000Hz SAMPLE_RATE, or butter() raises
    ValueError; see apply_lowpass()'s docstring for the full reasoning)
  - Spectral subtraction's over_subtract/floor/n_fft/hop parameters
  - DFN's atten_lim_db (currently 30 — see the long comment inside
    apply_deepfilternet() for why this isn't 12, and isn't None/unbounded
    either; this went through two documented revisions and is the single
    most consequential tuning value in the whole pipeline)
  - Whether DFN's post_filter is enabled (currently True)

DO NOT tune AGC/compressor/limiter here even though they also affect
perceived "cleanliness" — those live in dynamics.py. This file's job is
strictly "reduce the noise energy," not "manage the resulting loudness."

Order matters: this module must run AFTER vad_gate.py's gating (the VAD
gate zeroes non-speech before DFN sees it, which is part of what protects
quiet speech from being classified as "confident noise" by DFN) and
BEFORE dynamics.py's AGC (AGC needs to boost a signal that's already had
its noise floor lowered, not the other way around).
"""

import os
import sys
import types
from dataclasses import dataclass
import numpy as np
import torch
from scipy.signal import butter, sosfiltfilt

# Compatibility shim for DeepFilterNet on newer torchaudio versions (2.1+ / 2.12+)
# where torchaudio.backend.common.AudioMetaData was removed from torchaudio.
if "torchaudio.backend" not in sys.modules:
    try:
        @dataclass
        class AudioMetaData:
            sample_rate: int = 16000
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
    except Exception:
        pass

torch.set_grad_enabled(False)

SAMPLE_RATE = 16000


def apply_highpass(audio_data):
    """Stage 1: removes rumble below 80Hz using numerically stable SOS filter."""
    sos = butter(4, 80 / (SAMPLE_RATE / 2), btype='high', output='sos')
    return sosfiltfilt(sos, audio_data).astype(np.float32)


def apply_lowpass(audio_data, cutoff_hz=7500):
    """
    Stage 1b (optional): caps frequencies above cutoff_hz (default 7500Hz).
    Uses 4th-order Butterworth SOS filter, zero-phase.
    Cutoff must stay below Nyquist (8000Hz at 16kHz sample rate).
    """
    sos = butter(4, cutoff_hz / (SAMPLE_RATE / 2), btype='low', output='sos')
    return sosfiltfilt(sos, audio_data).astype(np.float32)


def spectral_subtract(signal, over_subtract=2.0, floor=0.05, n_fft=512, hop=128):
    """
    Stage 1.5: STFT-domain noise separation. Estimates a noise spectrum
    from the quietest 15% of frames (by energy) across the whole signal,
    then subtracts an over_subtract-scaled version of it from every
    frame's magnitude spectrum, with a floor to avoid musical-noise
    artifacts from over-subtracting.
    """
    if len(signal) < n_fft:
        print(f"PROGRESS: spectral_subtract skipped, input too short ({len(signal)} samples)")
        return signal

    import librosa
    D = librosa.stft(signal, n_fft=n_fft, hop_length=hop, win_length=n_fft, window='hann')
    mag = np.abs(D)
    phase = np.angle(D)

    frame_energy = np.sum(mag ** 2, axis=0)
    noise_thresh = np.percentile(frame_energy, 15)
    noise_frames = mag[:, frame_energy <= noise_thresh]
    if noise_frames.shape[1] == 0:
        noise_frames = mag[:, :max(1, int(mag.shape[1] * 0.15))]

    noise_spectrum = np.mean(noise_frames, axis=1, keepdims=True)
    subtracted_mag = np.maximum(mag - over_subtract * noise_spectrum, floor * mag)
    D_clean = subtracted_mag * np.exp(1j * phase)

    result = librosa.istft(D_clean, hop_length=hop, win_length=n_fft, window='hann', length=len(signal))
    return result.astype(np.float32)



def apply_deepfilternet(audio_data, atten_lim_db=30, post_filter=False):
    """
    Stage 3: DeepFilterNet, the neural denoiser.
    atten_lim_db caps per-bin suppression (e.g. 18dB for gentle, 30dB for balanced, 36dB for aggressive).
    """
    global _CACHED_DF_MODEL, _CACHED_DF_STATE, _CACHED_DF_POSTFILTER
    try:
        from df.enhance import enhance, init_df
    except ImportError as e:
        print(f"PROGRESS: DeepFilterNet neural denoiser not available ({e}), bypassing neural stage")
        return audio_data

    try:
        if _CACHED_DF_MODEL is None or _CACHED_DF_STATE is None or _CACHED_DF_POSTFILTER != post_filter:
            try:
                torch.set_num_threads(min(4, max(1, os.cpu_count() or 2)))
            except Exception:
                pass
            _CACHED_DF_MODEL, _CACHED_DF_STATE, _ = init_df(post_filter=post_filter)
            _CACHED_DF_POSTFILTER = post_filter

        audio_tensor = torch.from_numpy(audio_data[np.newaxis, :]).float()
        with torch.inference_mode():
            result = enhance(
                _CACHED_DF_MODEL,
                _CACHED_DF_STATE,
                audio_tensor,
                atten_lim_db=atten_lim_db
            ).squeeze().numpy().astype(np.float32)
        return result
    except Exception as exc:
        print(f"PROGRESS: DeepFilterNet processing fallback ({exc})")
        return audio_data

_CACHED_DF_MODEL = None
_CACHED_DF_STATE = None
_CACHED_DF_POSTFILTER = None



MODE_SETTINGS = {
    "gentle": {"over_subtract": 1.2, "floor": 0.10, "atten_lim_db": 18, "post_filter": False},
    "balanced": {"over_subtract": 2.0, "floor": 0.05, "atten_lim_db": 30, "post_filter": False},
    "aggressive": {"over_subtract": 2.8, "floor": 0.02, "atten_lim_db": 36, "post_filter": True},
}


def process(audio_data, mode="balanced"):
    """Runs all three noise-removal sub-stages in order with mode parameters.
    Modes:
      - 'gentle': 18dB cap, milder suppression for light room hum or studio voiceovers.
      - 'balanced': 30dB cap, standard balanced suppression.
      - 'aggressive': 36dB cap with post_filter, higher over-subtraction for noisy environments.
    """
    settings = MODE_SETTINGS.get(mode, MODE_SETTINGS["balanced"])
    audio_data = apply_highpass(audio_data)
    audio_data = spectral_subtract(
        audio_data,
        over_subtract=settings["over_subtract"],
        floor=settings["floor"]
    )
    audio_data = apply_deepfilternet(
        audio_data,
        atten_lim_db=settings["atten_lim_db"],
        post_filter=settings.get("post_filter", False)
    )
    return audio_data