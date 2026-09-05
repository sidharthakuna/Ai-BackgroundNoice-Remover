"""
dsp.py — Studio 48kHz audio DSP processing algorithms.
Includes 75Hz rumble filter, Wiener spectral gating, dual-band VAD,
broadcast dynamics (AGC leveler, compressor, soft-knee limiter),
5-band voice mastering EQ, dynamic de-esser, and ITU-R BS.1770-4 loudness normalization.
"""

import gc
import numpy as np
import scipy.signal
import scipy.ndimage
from scipy.signal import butter, sosfiltfilt, stft, istft
from app.config import SAMPLE_RATE


def apply_highpass(audio: np.ndarray, cutoff_hz: float = 75.0) -> np.ndarray:
    """Removes sub-bass rumble (< 75Hz) using a 4th-order Butterworth filter."""
    if len(audio) < 100:
        return audio.astype(np.float32)
    nyquist = SAMPLE_RATE / 2.0
    normalized_cutoff = min(cutoff_hz / nyquist, 0.99)
    sos = butter(4, normalized_cutoff, btype="high", output="sos")
    return sosfiltfilt(sos, audio).astype(np.float32)


def apply_spectral_gating(signal: np.ndarray, over_subtract: float = 1.8, floor: float = 0.08,
                          n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """
    Wiener-style smoothed multi-band STFT spectral gating.
    Applies 3-frame temporal smoothing to gain masks to eliminate musical tone flutter.
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

    # 3-frame temporal smoothing across time prevents musical flutter
    smooth_gain = scipy.ndimage.uniform_filter1d(gain_mask, size=3, axis=1)

    cleaned_mag = mag * smooth_gain
    del mag, noise_spectrum, snr_est, gain_mask, smooth_gain

    D_clean = cleaned_mag * np.exp(1j * phase)
    del cleaned_mag, phase

    _, result = istft(D_clean, fs=SAMPLE_RATE, window="hann", nperseg=n_fft, noverlap=n_fft - hop)
    del D_clean

    gc.collect()
    return result[:len(signal)].astype(np.float32)


def apply_vad_gating(audio: np.ndarray, aggressiveness: int = 2, floor_db: float = -28.0) -> np.ndarray:
    """
    Dual-band Voice Activity Detector with lookahead & hangover dilation:
    Combines WebRTC VAD with 200-3400Hz speech-formant energy ratio.
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

    frame_ms = 30
    frame_len_16k = int(vad_sr * frame_ms / 1000)
    num_frames = len(audio_16k) // frame_len_16k

    if num_frames < 2:
        return audio.astype(np.float32)

    vad = webrtcvad.Vad(min(max(aggressiveness, 0), 3))
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
    smooth_frame_gain = scipy.ndimage.gaussian_filter1d(frame_gain, sigma=2.5)

    # Interpolate gain curve back up to 48kHz
    frame_times_16k = np.arange(num_frames) * frame_len_16k + frame_len_16k / 2
    sample_times_16k = np.arange(len(audio_16k))
    gain_16k = np.interp(sample_times_16k, frame_times_16k, smooth_frame_gain)

    gain_48k = np.interp(np.linspace(0, 1, len(audio)), np.linspace(0, 1, len(gain_16k)), gain_16k).astype(np.float32)
    return (audio * gain_48k).astype(np.float32)


def apply_dynamics(audio: np.ndarray, comp_ratio: float = 3.5, target_peak: float = 0.92) -> np.ndarray:
    """
    Broadcast Dynamics Processing:
    1. Sliding-window RMS AGC speech leveler.
    2. RMS compressor (-26dB threshold, 3.5:1 ratio).
    3. Soft-knee peak limiter.
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
        target_rms = 0.10
        raw_gain = np.clip(target_rms / frame_rms, 0.4, 2.5)
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


def apply_tone_mastering(audio: np.ndarray, target_lufs: float = -14.0) -> np.ndarray:
    """5-Band Studio Voice Parametric EQ, Dynamic De-Esser & ITU-R BS.1770-4 Loudness Normalization."""
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

    eq_audio = peaking_eq(audio, 160.0, 1.2, 1.0)     # Warmth
    eq_audio = peaking_eq(eq_audio, 420.0, -1.8, 1.2) # Boxiness cut
    eq_audio = peaking_eq(eq_audio, 1000.0, 1.0, 1.0) # Clarity
    eq_audio = peaking_eq(eq_audio, 3200.0, 2.0, 1.2) # Presence
    eq_audio = peaking_eq(eq_audio, 8500.0, 1.5, 0.8) # Air

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
        rms = np.sqrt(np.mean(deessed ** 2) + 1e-9)
        target_rms = 10.0 ** (-16.0 / 20.0)
        gain = np.clip(target_rms / rms, 0.1, 4.0)
        deessed = deessed * gain

    # True-peak guard
    peak = np.max(np.abs(deessed)) + 1e-9
    if peak > 0.95:
        deessed = (deessed / peak) * 0.95

    return deessed.astype(np.float32)
