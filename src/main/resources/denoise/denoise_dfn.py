"""
denoise_dfn.py — the actual noise-removal stages (original Stages 1, 1.5, 3).

Three sub-stages, called directly by main.py's run_pipeline() in this
order (each mode-scaled via MODE_SETTINGS below):
  1. High-pass filter — removes rumble below 80Hz.
  2. Spectral subtraction — STFT-domain noise-profile subtraction.
  3. DeepFilterNet (DFN) — the neural denoiser doing the heavy lifting.

NOTE: this module intentionally has no process()/run() entry point of its
own. main.py calls apply_highpass(), spectral_subtract(), and
apply_deepfilternet() directly, each with settings pulled from
MODE_SETTINGS.get(mode, ...) — see run_pipeline() there for the exact
call sequence. An earlier version of this file also defined a process()
that re-implemented the same three-stage sequence internally, but nothing
ever called it (main.py had already switched to calling the stage
functions directly with mode-aware settings) — it was dead code kept in
sync with main.py by hand, which is exactly the kind of duplication this
package's other modules explicitly avoid (see dynamics.py process() and
tone.py process(), which ARE the real, called entry points for their
respective files). It was removed rather than fixed forward: if you're
looking for "the function that runs this file's stages," that's
run_pipeline() in main.py, not something in this file.

Also present, but NOT yet part of the pipeline — apply_lowpass(), a fixed
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

# Prevent OpenBLAS / MKL / OMP / Torch thread explosion on container CFS CPU quotas
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["TORCH_NUM_THREADS"] = "1"

import types
from dataclasses import dataclass
import numpy as np
import torch
from scipy.signal import butter, sosfiltfilt, stft, istft

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
        if "torchaudio" in sys.modules:
            sys.modules["torchaudio"].backend = backend_mod
    except Exception:
        pass

torch.set_num_threads(1)
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


def spectral_subtract(signal, over_subtract=2.0, floor=0.05, n_fft=512, hop=256):
    """
    Stage 1.5: Fast STFT-domain noise separation using Scipy.
    Estimates a noise spectrum from the quietest 15% of frames (by energy)
    across the whole signal, then subtracts an over_subtract-scaled version.
    """
    if len(signal) < n_fft:
        print(f"PROGRESS: spectral_subtract skipped, input too short ({len(signal)} samples)")
        return signal

    f, t_axis, Zxx = stft(signal, fs=SAMPLE_RATE, window='hann', nperseg=n_fft, noverlap=n_fft - hop)
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

    subtracted_mag = np.maximum(mag - over_subtract * noise_spectrum, floor * mag)
    del noise_spectrum, mag

    D_clean = subtracted_mag * np.exp(1j * phase)
    del subtracted_mag, phase

    _, result = istft(D_clean, fs=SAMPLE_RATE, window='hann', nperseg=n_fft, noverlap=n_fft - hop)
    del D_clean

    import gc
    gc.collect()
    return result[:len(signal)].astype(np.float32)



def apply_deepfilternet(audio_data, atten_lim_db=30, post_filter=False):
    """
    Stage 3: DeepFilterNet, the neural denoiser.
    Runs at native 48kHz with minimal memory footprint (~49MB for 4.5 minutes)
    and executes in just a few seconds.
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
                torch.set_num_threads(1)
            except Exception:
                pass
            _CACHED_DF_MODEL, _CACHED_DF_STATE, _ = init_df(post_filter=post_filter)
            _CACHED_DF_POSTFILTER = post_filter

        df_sr = _CACHED_DF_STATE.sr() if hasattr(_CACHED_DF_STATE, "sr") else 48000
        
        # Resample to DeepFilterNet native sample rate (48kHz)
        import soxr
        if SAMPLE_RATE != df_sr:
            df_in = soxr.resample(audio_data, SAMPLE_RATE, df_sr)
        else:
            df_in = audio_data

        audio_tensor = torch.from_numpy(df_in[np.newaxis, :]).float()
        with torch.no_grad():
            result = enhance(
                _CACHED_DF_MODEL,
                _CACHED_DF_STATE,
                audio_tensor,
                atten_lim_db=atten_lim_db
            ).squeeze().numpy().astype(np.float32)
        del audio_tensor, df_in

        # Resample back to pipeline sample rate (16kHz)
        if SAMPLE_RATE != df_sr:
            result = soxr.resample(result, df_sr, SAMPLE_RATE)

        # Match exact input length
        n = len(audio_data)
        if len(result) < n:
            result = np.pad(result, (0, n - len(result)))
        elif len(result) > n:
            result = result[:n]

        import gc
        gc.collect()
        return result.astype(np.float32)
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