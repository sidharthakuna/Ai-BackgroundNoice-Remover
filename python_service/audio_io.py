"""
audio_io.py — High-fidelity 48kHz audio I/O with Mid/Side channel separation and true-peak protection.
"""

import os
import subprocess
import numpy as np
import soundfile as sf
import scipy.signal

SAMPLE_RATE = 48000


def load_audio(path: str):
    """
    Loads audio file into float32 numpy array at 48000Hz.
    Returns:
        audio: np.ndarray shape (N,) for mono or (2, N) for stereo.
        sr: int (always 48000)
        is_stereo: bool
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input audio file not found: {path}")

    try:
        data, orig_sr = sf.read(path, dtype="float32", always_2d=True)
    except Exception as exc:
        # Fallback to ffmpeg decode if soundfile can't decode container
        data, orig_sr = _load_via_ffmpeg(path)

    # data is (samples, channels)
    num_samples, num_channels = data.shape

    # Check for empty file
    if num_samples == 0:
        raise ValueError("Audio file contains 0 audio samples.")

    # Resample to 48000Hz if needed
    if orig_sr != SAMPLE_RATE:
        data = _resample(data, orig_sr, SAMPLE_RATE)

    # Convert to channels-first: shape (channels, samples)
    data = data.T

    # If multichannel > 2, mixdown or take first 2 channels
    if data.shape[0] > 2:
        data = data[:2, :]

    if data.shape[0] == 1:
        return data[0], SAMPLE_RATE, False

    # Stereo check: measure correlation between left and right channels
    left = data[0]
    right = data[1]
    norm_l = np.linalg.norm(left)
    norm_r = np.linalg.norm(right)
    if norm_l > 1e-6 and norm_r > 1e-6:
        correlation = np.dot(left, right) / (norm_l * norm_r)
    else:
        correlation = 1.0

    # If correlation is >= 0.98, it's essentially identical dual-mono: fold to mono to save 50% RAM & CPU
    if correlation >= 0.98:
        mono = ((left + right) * 0.5).astype(np.float32)
        return mono, SAMPLE_RATE, False

    return data.astype(np.float32), SAMPLE_RATE, True


def save_audio(path: str, audio: np.ndarray, sr: int = SAMPLE_RATE, subtype: str = "PCM_24"):
    """
    Saves audio numpy array safely to disk at 48000Hz with true-peak ceiling protection.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    # Audio shape: if (2, N), transpose to (N, 2)
    if audio.ndim == 2:
        if audio.shape[0] == 2:
            out_data = audio.T
        else:
            out_data = audio
    else:
        out_data = audio

    # Apply true-peak ceiling: limit to 0.95 (-0.45 dBFS) to prevent inter-sample clipping
    peak = np.max(np.abs(out_data))
    if peak > 0.95:
        out_data = (out_data / peak) * 0.95

    sf.write(path, out_data, sr, subtype=subtype)


def encode_mid_side(stereo_audio: np.ndarray):
    """
    Converts 2-channel stereo (left, right) to Mid/Side:
    Mid = (L + R) / sqrt(2)  (contains center speech/vocals)
    Side = (L - R) / sqrt(2) (contains ambient stereo reverb and width)
    """
    left = stereo_audio[0]
    right = stereo_audio[1]
    mid = (left + right) / np.sqrt(2.0)
    side = (left - right) / np.sqrt(2.0)
    return mid.astype(np.float32), side.astype(np.float32)


def decode_mid_side(mid: np.ndarray, side: np.ndarray):
    """
    Reconstructs 2-channel stereo from Mid/Side:
    Left = (Mid + Side) / sqrt(2)
    Right = (Mid - Side) / sqrt(2)
    """
    min_len = min(len(mid), len(side))
    m = mid[:min_len]
    s = side[:min_len]
    left = (m + s) / np.sqrt(2.0)
    right = (m - s) / np.sqrt(2.0)
    return np.vstack([left, right]).astype(np.float32)


def _resample(data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    try:
        import soxr
        return soxr.resample(data, orig_sr, target_sr, quality="HQ").astype(np.float32)
    except Exception:
        pass

    gcd = np.gcd(orig_sr, target_sr)
    up = target_sr // gcd
    down = orig_sr // gcd
    return scipy.signal.resample_poly(data, up, down, axis=0).astype(np.float32)


def _load_via_ffmpeg(path: str):
    cmd = [
        "ffmpeg", "-v", "error", "-i", path,
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ar", str(SAMPLE_RATE), "-"
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    return audio.reshape(-1, 1), SAMPLE_RATE
