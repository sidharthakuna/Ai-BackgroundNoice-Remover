"""
vad.py — Dual-band Voice Activity Detector (VAD) gating.
Combines WebRTC VAD with 200–3400Hz speech-formant energy detection.
Applies 180ms lookahead dilation and 300ms hangover smoothing to protect word edges.
"""

import numpy as np
import scipy.signal
import scipy.ndimage
from scipy.signal import butter, sosfiltfilt
from python_service.config import SAMPLE_RATE


def apply_vad_gating(audio: np.ndarray, aggressiveness: int = 2, floor_db: float = -28.0) -> np.ndarray:
    """
    Dual-band Voice Activity Detector with lookahead & hangover dilation:
    1. Downsamples to 16kHz for WebRTC VAD.
    2. Measures 200-3400Hz speech formant energy ratio.
    3. Dilates speech regions by 180ms lookahead + 300ms hangover to prevent word cutoffs.
    4. Smooths gain curve with Gaussian filter and interpolates back to 48kHz.
    """
    try:
        import webrtcvad
    except ImportError:
        return audio.astype(np.float32)

    vad_sr = 16000
    num_vad_samples = int(len(audio) * vad_sr / SAMPLE_RATE)
    if num_vad_samples < 480:
        return audio.astype(np.float32)

    audio_16k = scipy.signal.resample(audio, num_vad_samples).astype(np.float32)

    # 30ms frames = 480 samples at 16kHz
    frame_ms = 30
    frame_len_16k = int(vad_sr * frame_ms / 1000)
    num_frames = len(audio_16k) // frame_len_16k

    if num_frames < 2:
        return audio.astype(np.float32)

    vad = webrtcvad.Vad(min(max(aggressiveness, 0), 3))

    # Scale to 16-bit PCM for WebRTC
    pcm_16k = np.clip(audio_16k * 32767, -32768, 32767).astype(np.int16)

    # Formant bandpass: 200Hz - 3400Hz
    sos_formant = butter(2, [200.0 / (vad_sr / 2), 3400.0 / (vad_sr / 2)], btype="bandpass", output="sos")
    formant_audio = sosfiltfilt(sos_formant, audio_16k)

    frame_is_speech = np.zeros(num_frames, dtype=bool)
    for i in range(num_frames):
        start = i * frame_len_16k
        end = start + frame_len_16k
        chunk_bytes = pcm_16k[start:end].tobytes()
        try:
            webrtc_speech = vad.is_speech(chunk_bytes, vad_sr)
        except Exception:
            webrtc_speech = True

        formant_energy = np.mean(formant_audio[start:end] ** 2)
        total_energy = np.mean(audio_16k[start:end] ** 2) + 1e-9
        formant_ratio = formant_energy / total_energy
        energy_speech = formant_ratio > 0.35 and total_energy > 1e-5

        frame_is_speech[i] = webrtc_speech or energy_speech

    # Lookahead (180ms = 6 frames) + Hangover (300ms = 10 frames)
    dilation_structure = np.ones(6 + 1 + 10, dtype=bool)
    dilated_speech = scipy.ndimage.binary_dilation(frame_is_speech, structure=dilation_structure)

    # Convert binary mask to smooth gain curve
    frame_gain = np.where(dilated_speech, 1.0, 10.0 ** (floor_db / 20.0)).astype(np.float32)
    # Gaussian smoothing across frames
    smooth_frame_gain = scipy.ndimage.gaussian_filter1d(frame_gain, sigma=2.5)

    # Interpolate gain curve back up to 16kHz sample positions
    frame_times_16k = np.arange(num_frames) * frame_len_16k + frame_len_16k / 2
    sample_times_16k = np.arange(len(audio_16k))
    gain_16k = np.interp(sample_times_16k, frame_times_16k, smooth_frame_gain)

    # Resample gain curve to 48kHz audio length
    gain_48k = np.interp(np.linspace(0, 1, len(audio)), np.linspace(0, 1, len(gain_16k)), gain_16k).astype(np.float32)

    return (audio * gain_48k).astype(np.float32)
