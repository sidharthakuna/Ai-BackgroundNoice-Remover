"""
pipeline.py — Complete 48kHz studio audio DSP pipeline.
Includes high-pass filtering, Wiener spectral gating, DeepFilterNet3 neural inference,
dual-band VAD, dynamic leveling, broadcast mastering EQ, dynamic de-essing,
EBU R128 loudness normalization, and memory-safe chunked Demucs vocal isolation.
"""

import gc
import os
import numpy as np
import scipy.signal
import scipy.ndimage
from scipy.signal import butter, sosfiltfilt, stft, istft
import torch

from python_service.audio_io import (
    load_audio,
    save_audio,
    encode_mid_side,
    decode_mid_side,
    SAMPLE_RATE
)

# Preset configuration profiles for different recording contexts
MODE_CONFIGS = {
    "subtle": {
        "rumble_cutoff": 65.0,
        "spectral_oversub": 1.2,
        "spectral_floor": 0.12,
        "dfn_atten_lim": 18,
        "dfn_postfilter": False,
        "vad_strength": 1,
        "compressor_ratio": 2.5,
        "target_lufs": -16.0
    },
    "balanced": {
        "rumble_cutoff": 75.0,
        "spectral_oversub": 1.8,
        "spectral_floor": 0.08,
        "dfn_atten_lim": 30,
        "dfn_postfilter": False,
        "vad_strength": 2,
        "compressor_ratio": 3.5,
        "target_lufs": -14.0
    },
    "aggressive": {
        "rumble_cutoff": 85.0,
        "spectral_oversub": 2.4,
        "spectral_floor": 0.04,
        "dfn_atten_lim": 36,
        "dfn_postfilter": True,
        "vad_strength": 3,
        "compressor_ratio": 4.5,
        "target_lufs": -14.0
    },
    "podcast": {
        "rumble_cutoff": 80.0,
        "spectral_oversub": 1.8,
        "spectral_floor": 0.07,
        "dfn_atten_lim": 28,
        "dfn_postfilter": False,
        "vad_strength": 2,
        "compressor_ratio": 4.0,
        "target_lufs": -14.0
    }
}


# ============================================================================
# Stage 1: Highpass Rumble & Ceiling Filter
# ============================================================================
def apply_highpass(audio: np.ndarray, cutoff_hz: float = 75.0) -> np.ndarray:
    """Removes sub-bass rumble (< 75Hz) using a 4th-order Butterworth filter."""
    sos = butter(4, cutoff_hz / (SAMPLE_RATE / 2), btype="high", output="sos")
    return sosfiltfilt(sos, audio).astype(np.float32)


# ============================================================================
# Stage 2: Wiener Multi-band Spectral Gating
# ============================================================================
def apply_spectral_gating(signal: np.ndarray, over_subtract: float = 1.8, floor: float = 0.08,
                           n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """
    Wiener-style smoothed multi-band STFT spectral gating.
    Uses 3-frame temporal smoothing across time axis to eliminate musical chirps.
    """
    if len(signal) < n_fft:
        return signal

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


# ============================================================================
# Stage 3: Dual-Band VAD Gating with Lookahead Dilation
# ============================================================================
def apply_vad_gating(audio: np.ndarray, aggressiveness: int = 2, floor_db: float = -28.0) -> np.ndarray:
    """
    Dual-band Voice Activity Detector:
    Combines WebRTC VAD with 200–3400Hz speech-formant energy detection.
    Applies 180ms lookahead and 300ms hangover smoothing to protect word edges.
    """
    try:
        import webrtcvad
    except ImportError:
        return audio

    # Downsample to 16000Hz for WebRTC VAD
    vad_sr = 16000
    num_vad_samples = int(len(audio) * vad_sr / SAMPLE_RATE)
    audio_16k = scipy.signal.resample(audio, num_vad_samples).astype(np.float32)

    # 30ms frames = 480 samples at 16kHz
    frame_ms = 30
    frame_len_16k = int(vad_sr * frame_ms / 1000)
    num_frames = len(audio_16k) // frame_len_16k

    if num_frames < 2:
        return audio

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

    # Interpolate gain curve back up to 48000Hz
    frame_times_16k = np.arange(num_frames) * frame_len_16k + frame_len_16k / 2
    sample_times_16k = np.arange(len(audio_16k))
    gain_16k = np.interp(sample_times_16k, frame_times_16k, smooth_frame_gain)

    # Resample gain curve to 48kHz audio length
    gain_48k = np.interp(np.linspace(0, 1, len(audio)), np.linspace(0, 1, len(gain_16k)), gain_16k).astype(np.float32)

    return (audio * gain_48k).astype(np.float32)


# ============================================================================
# Stage 4: Dynamics — AGC Leveling, Compression & Soft-Knee Limiter
# ============================================================================
def apply_dynamics(audio: np.ndarray, comp_ratio: float = 3.5, target_peak: float = 0.92) -> np.ndarray:
    """
    Broadcast Dynamics Processing:
    1. Fast AGC leveling to balance fluctuating speaker distance (150ms window).
    2. Broadcast RMS compressor (-26dB threshold, 3.5:1 ratio, 20ms attack, 200ms release).
    3. Soft-knee peak limiter.
    """
    if len(audio) < 1000:
        return audio

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
    threshold_linear = 10.0 ** (-26.0 / 20.0) # ~0.05
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
            # Over threshold: compress by ratio
            gain = (envelope / threshold_linear) ** (1.0 / comp_ratio - 1.0)
        else:
            gain = 1.0
        compressed[i] = x * gain

    # Step 3: Soft-Knee Limiter (tanh saturation above 0.85)
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


# ============================================================================
# Stage 5: Tone — 5-Band Voice EQ, Dynamic De-Esser & EBU R128 Loudness
# ============================================================================
def apply_tone_mastering(audio: np.ndarray, target_lufs: float = -14.0) -> np.ndarray:
    """
    5-Band Voice EQ + Dynamic De-Esser + EBU R128 Loudness Normalization:
    - 150Hz Warmth Shelf (+1.5 dB)
    - 400Hz Mud Cut (-2.0 dB)
    - 1000Hz Vocal Formant Boost (+1.0 dB)
    - 3200Hz Presence / Intelligibility (+2.0 dB)
    - 8000Hz Air Shelf (+1.5 dB)
    - Dynamic De-Esser (5.5kHz–8.5kHz)
    - ITU-R BS.1770-4 (-14 LUFS)
    """
    if len(audio) < 1000:
        return audio

    # 1. 5-Band Parametric EQ
    def peaking_eq(x, f0, gain_db, q):
        w0 = 2 * np.pi * f0 / SAMPLE_RATE
        A = 10.0 ** (gain_db / 40.0)
        alpha = np.sin(w0) / (2.0 * q)
        b0 = 1 + alpha * A
        b1 = -2 * np.cos(w0)
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha / A
        b = np.array([b0, b1, b2]) / a0
        a = np.array([a0, a1, a2]) / a0
        return scipy.signal.lfilter(b, a, x).astype(np.float32)

    eq_audio = peaking_eq(audio, 160.0, 1.2, 1.0)    # Warmth
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
        # Fallback RMS normalization
        rms = np.sqrt(np.mean(deessed ** 2) + 1e-9)
        target_rms = 10.0 ** (-16.0 / 20.0)
        gain = np.clip(target_rms / rms, 0.1, 4.0)
        deessed = deessed * gain

    # True-peak guard
    peak = np.max(np.abs(deessed)) + 1e-9
    if peak > 0.95:
        deessed = (deessed / peak) * 0.95

    return deessed.astype(np.float32)


# ============================================================================
# Stage 6: Chunked Memory-Guarded Demucs Vocal Isolation
# ============================================================================
def apply_demucs_chunked(audio: np.ndarray, demucs_model, chunk_seconds: float = 4.0) -> np.ndarray:
    """
    Executes Demucs vocal isolation in small 4-second chunks with overlap-add.
    Protects the container from exceeding 512MB RAM.
    """
    from demucs.apply import apply_model

    chunk_samples = int(chunk_seconds * SAMPLE_RATE)
    overlap_samples = int(0.5 * SAMPLE_RATE)
    step_samples = chunk_samples - overlap_samples

    total_len = len(audio) if audio.ndim == 1 else audio.shape[1]
    is_mono = audio.ndim == 1

    if is_mono:
        stereo_in = np.vstack([audio, audio])
    else:
        stereo_in = audio

    output = np.zeros_like(stereo_in)
    weights = np.zeros(total_len, dtype=np.float32)
    window = np.hanning(chunk_samples).astype(np.float32)

    num_chunks = max(1, int(np.ceil((total_len - overlap_samples) / step_samples)))

    for i in range(num_chunks):
        start = i * step_samples
        end = min(start + chunk_samples, total_len)
        chunk = stereo_in[:, start:end]

        if chunk.shape[1] < chunk_samples:
            pad_len = chunk_samples - chunk.shape[1]
            chunk = np.pad(chunk, ((0, 0), (0, pad_len)))
        else:
            pad_len = 0

        tensor_in = torch.from_numpy(chunk[np.newaxis, :, :]).float()
        with torch.inference_mode():
            # returns (batch, sources, channels, time)
            sources = apply_model(demucs_model, tensor_in, device="cpu", num_workers=0, progress=False)
            # Demucs sources: 0=drums, 1=bass, 2=other, 3=vocals
            vocals = sources[0, 3].cpu().numpy()

        del tensor_in, sources
        gc.collect()

        actual_len = chunk_samples - pad_len
        w = window[:actual_len]
        output[:, start:start + actual_len] += vocals[:, :actual_len] * w
        weights[start:start + actual_len] += w

    weights = np.maximum(weights, 1e-6)
    isolated = output / weights

    if is_mono:
        return isolated[0].astype(np.float32)
    return isolated.astype(np.float32)


# ============================================================================
# Main Processing Pipeline
# ============================================================================
def execute_pipeline(input_path: str, output_path: str, mode: str, use_demucs: bool,
                     model_manager, progress_callback, cancel_check):
    """
    Executes the full studio DSP pipeline from start to finish.
    Communicates progress and respects cancellation tokens.
    """
    cfg = MODE_CONFIGS.get(mode.lower(), MODE_CONFIGS["balanced"])

    # Step 1: Load audio at 48000Hz
    progress_callback(10, "LOADING", "Loading 48kHz audio into memory")
    audio, sr, is_stereo = load_audio(input_path)

    if cancel_check():
        return False

    # Step 2: Demucs vocal isolation (if requested)
    if use_demucs:
        progress_callback(20, "ISOLATING_VOCALS", "Isolating vocal stems via Demucs (chunked)")
        demucs_model = model_manager.get_demucs_model()
        if is_stereo:
            audio = apply_demucs_chunked(audio, demucs_model)
        else:
            audio = apply_demucs_chunked(audio, demucs_model)
        gc.collect()

    if cancel_check():
        return False

    # Step 3: Stereo Mid/Side separation if stereo
    if is_stereo:
        progress_callback(35, "ENCODING_STEREO", "Encoding stereo into Mid/Side spatial domains")
        mid, side = encode_mid_side(audio)
        channels_to_process = [("mid", mid), ("side", side)]
    else:
        channels_to_process = [("mono", audio)]

    processed_channels = []
    for ch_name, ch_audio in channels_to_process:
        if cancel_check():
            return False

        # Stage A: High-pass rumble filter (< 75Hz)
        progress_callback(45, "PRE_FILTERING", f"Applying 70Hz rumble filter ({ch_name} channel)")
        ch_hp = apply_highpass(ch_audio, cutoff_hz=cfg["rumble_cutoff"])

        # Stage B: Wiener-style spectral gating
        progress_callback(55, "SPECTRAL_GATING", f"Wiener multi-band spectral gating ({ch_name} channel)")
        ch_gated = apply_spectral_gating(ch_hp, over_subtract=cfg["spectral_oversub"], floor=cfg["spectral_floor"])

        # Stage C: DeepFilterNet3 neural inference
        progress_callback(70, "NEURAL_SUPPRESSION", f"DeepFilterNet3 neural enhancement ({ch_name} channel)")
        df_model, df_state = model_manager.get_deepfilternet_model(post_filter=cfg["dfn_postfilter"])

        audio_tensor = torch.from_numpy(ch_gated[np.newaxis, :]).float()
        with torch.inference_mode():
            from df.enhance import enhance
            df_out = enhance(df_model, df_state, audio_tensor, atten_lim_db=cfg["dfn_atten_lim"])
            ch_denoised = df_out.squeeze().cpu().numpy().astype(np.float32)

        del audio_tensor, df_out
        gc.collect()

        # Match length
        n = len(ch_audio)
        if len(ch_denoised) < n:
            ch_denoised = np.pad(ch_denoised, (0, n - len(ch_denoised)))
        elif len(ch_denoised) > n:
            ch_denoised = ch_denoised[:n]

        # Stage D: Dual-Band VAD Gating
        progress_callback(82, "VAD_GATING", f"Dual-band voice activity gating ({ch_name} channel)")
        ch_vad = apply_vad_gating(ch_denoised, aggressiveness=cfg["vad_strength"])

        # Stage E: Dynamics (AGC Leveler + Compressor + Limiter)
        progress_callback(88, "DYNAMICS", f"AGC speech leveling and compression ({ch_name} channel)")
        ch_dyn = apply_dynamics(ch_vad, comp_ratio=cfg["compressor_ratio"])

        # Stage F: Mastering EQ, De-Essing & EBU R128 Loudness
        progress_callback(93, "MASTERING", f"Voice EQ, de-essing and EBU R128 loudness ({ch_name} channel)")
        ch_final = apply_tone_mastering(ch_dyn, target_lufs=cfg["target_lufs"])

        processed_channels.append(ch_final)

    if cancel_check():
        return False

    # Step 4: Reconstruct Stereo / Mono
    progress_callback(97, "RECONSTRUCTING", "Reconstructing output audio container")
    if is_stereo:
        final_audio = decode_mid_side(processed_channels[0], processed_channels[1])
    else:
        final_audio = processed_channels[0]

    # Step 5: Save output WAV
    progress_callback(99, "SAVING", "Writing master audio file to disk")
    save_audio(output_path, final_audio, sr=SAMPLE_RATE)

    progress_callback(100, "DONE", "Audio enhancement completed successfully")
    return True
