"""
vad_gate.py — Dual-band Voice Activity Detection with mumble recovery and lookahead gating.
"""

import numpy as np
import scipy.ndimage
from scipy.signal import butter, sosfilt
import webrtcvad

SAMPLE_RATE = 48000
VAD_SR = 16000


def apply_vad_gate(audio_data):
    """
    Runs VAD at 16kHz while preserving 48kHz studio audio.
    Combines webrtcvad with a 200-3400Hz formant-band energy analyzer to detect quiet mumbles.
    Returns (gated_audio, vad_gain) at 48kHz.
    """
    min_analyzable_samples = int(SAMPLE_RATE * 0.320)
    if len(audio_data) < min_analyzable_samples:
        print(f"PROGRESS: vad_gate skipped, input too short ({len(audio_data)} samples)", flush=True)
        vad_gain = np.full(len(audio_data), 1.0, dtype=np.float32)
        return audio_data.astype(np.float32), vad_gain

    # Resample to 16kHz for WebRTC VAD
    import soxr
    audio_16k = soxr.resample(audio_data, SAMPLE_RATE, VAD_SR)

    frame_length = int(VAD_SR * 0.030)  # 30ms frame = 480 samples at 16kHz
    pcm16 = (np.clip(audio_16k, -1.0, 1.0) * 32767).astype(np.int16)

    remainder = len(pcm16) % frame_length
    if remainder:
        pcm16 = np.pad(pcm16, (0, frame_length - remainder), mode="constant")

    # Speech formant bandpass (200Hz - 3400Hz)
    sos_speech = butter(4, [200 / (VAD_SR / 2), 3400 / (VAD_SR / 2)], btype="band", output="sos")
    filtered_energy = sosfilt(sos_speech, audio_16k)

    rem_f = len(filtered_energy) % frame_length
    padded_energy = np.pad(filtered_energy, (0, frame_length - rem_f if rem_f else 0))
    reshaped = padded_energy.reshape(-1, frame_length)
    frame_rms = np.sqrt(np.mean(reshaped.astype(np.float32) ** 2, axis=1) + 1e-12)

    noise_floor = float(np.percentile(frame_rms, 20))
    mumble_threshold = max(1e-6, noise_floor * 3.5)

    vad_detector = webrtcvad.Vad(0)  # Level 0 = least aggressive, keeps soft speech
    num_frames = len(pcm16) // frame_length
    pcm_bytes = pcm16.tobytes()
    bytes_per_frame = frame_length * 2

    frame_speech_mask = np.zeros(num_frames, dtype=bool)
    for idx in range(num_frames):
        b_offset = idx * bytes_per_frame
        frame_bytes = pcm_bytes[b_offset: b_offset + bytes_per_frame]
        vad_says = vad_detector.is_speech(frame_bytes, VAD_SR)
        energy_says = (frame_rms[idx] > mumble_threshold) if idx < len(frame_rms) else False

        if vad_says or energy_says:
            frame_speech_mask[idx] = True

    # Lookahead frame dilation (~180ms = 6 frames)
    exp_frames = int(np.ceil(0.180 / 0.030))
    expanded_mask = scipy.ndimage.binary_dilation(
        frame_speech_mask, structure=np.ones(exp_frames * 2 + 1)
    )

    down_target = np.where(expanded_mask, 1.0, 0.20).astype(np.float32)
    eff_sr = VAD_SR / frame_length  # ~33.3 Hz
    att_a = np.exp(-1.0 / (eff_sr * 0.030))
    rel_a = np.exp(-1.0 / (eff_sr * 0.150))

    down_vad = np.empty_like(down_target)
    down_vad[0] = down_target[0]
    for i in range(1, len(down_target)):
        a = att_a if down_target[i] > down_vad[i - 1] else rel_a
        down_vad[i] = a * down_vad[i - 1] + (1.0 - a) * down_target[i]

    # Map back to 48kHz audio domain
    frame_centers_48k = (np.arange(num_frames) * frame_length + frame_length // 2) * (SAMPLE_RATE / VAD_SR)
    vad_gain = np.interp(
        np.arange(len(audio_data)),
        frame_centers_48k,
        down_vad,
        left=down_vad[0],
        right=down_vad[-1]
    ).astype(np.float32)

    gated_audio = (audio_data * vad_gain).astype(np.float32)
    return gated_audio, vad_gain