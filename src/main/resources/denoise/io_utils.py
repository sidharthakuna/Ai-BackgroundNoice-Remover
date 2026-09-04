"""
io_utils.py — Audio loading, 48kHz studio resampling, stereo correlation analysis, and saving.
"""

import os
import numpy as np
import soundfile as sf
import librosa

SAMPLE_RATE = 48000  # Studio rate (20Hz - 24kHz bandwidth)


def validate_input_path(input_path):
    """Raises if input file is missing or empty."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"input file not found: {input_path}")
    if os.path.getsize(input_path) == 0:
        raise ValueError("input file is empty")


def load_and_split_channels(input_path):
    """
    Loads audio, resamples to 48kHz studio rate, and analyzes stereo correlation.
    Returns:
      audio_data: mono signal for processing (mid channel for real stereo)
      side_channel: attenuated (L-R)/2 side channel if real stereo
      is_stereo: whether input was stereo
      source_is_real_stereo: whether channels carry true stereo information (correlation < 0.98)
    """
    validate_input_path(input_path)

    try:
        raw_audio, sr = sf.read(str(input_path), dtype="float32", always_2d=False)
        if raw_audio.ndim == 2:
            raw_audio = raw_audio.T
        if sr != SAMPLE_RATE:
            try:
                import soxr
                if raw_audio.ndim == 2:
                    ch0 = soxr.resample(raw_audio[0], sr, SAMPLE_RATE)
                    ch1 = soxr.resample(raw_audio[1], sr, SAMPLE_RATE)
                    raw_audio = np.stack([ch0, ch1])
                else:
                    raw_audio = soxr.resample(raw_audio, sr, SAMPLE_RATE)
            except Exception:
                raw_audio, _ = librosa.load(str(input_path), sr=SAMPLE_RATE, mono=False)
    except Exception:
        raw_audio, _ = librosa.load(str(input_path), sr=SAMPLE_RATE, mono=False)

    raw_audio = np.nan_to_num(raw_audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    # Downmix multi-channel audio (>2 channels, e.g. 5.1 surround)
    if raw_audio.ndim == 2 and raw_audio.shape[0] > 2:
        num_ch = raw_audio.shape[0]
        if num_ch == 6:  # 5.1: L, R, C, LFE, Ls, Rs
            left = raw_audio[0] + 0.7071 * raw_audio[2] + 0.7071 * raw_audio[4]
            right = raw_audio[1] + 0.7071 * raw_audio[2] + 0.7071 * raw_audio[5]
            raw_audio = np.stack([left, right])
        else:
            mid = np.mean(raw_audio, axis=0)
            raw_audio = np.stack([mid, mid])

    is_stereo = raw_audio.ndim == 2 and raw_audio.shape[0] == 2

    if is_stereo:
        left_channel = raw_audio[0]
        right_channel = raw_audio[1]
        std_l = float(np.std(left_channel))
        std_r = float(np.std(right_channel))

        if std_l > 1e-6 and std_r > 1e-6:
            cov = np.corrcoef(left_channel, right_channel)
            correlation = float(cov[0, 1]) if cov.ndim == 2 else 1.0
            source_is_real_stereo = bool(np.isfinite(correlation) and correlation < 0.98)
        else:
            source_is_real_stereo = False
    else:
        source_is_real_stereo = False

    if is_stereo and source_is_real_stereo:
        mid_channel = ((left_channel + right_channel) / 2.0).astype(np.float32)
        side_channel = (((left_channel - right_channel) / 2.0) * 0.15).astype(np.float32)
        audio_data = mid_channel
    elif is_stereo:
        # Mono wrapped in stereo container
        audio_data = ((left_channel + right_channel) / 2.0).astype(np.float32)
        side_channel = None
    else:
        audio_data = (raw_audio[0] if raw_audio.ndim == 2 else raw_audio).astype(np.float32)
        side_channel = None

    return {
        "audio_data": audio_data,
        "side_channel": side_channel,
        "is_stereo": is_stereo,
        "source_is_real_stereo": source_is_real_stereo,
    }


def reconstruct_output(audio_data, side_channel, is_stereo, source_is_real_stereo):
    """Reconstructs final stereo or mono output with a 0.95 true-peak ceiling."""
    if is_stereo and source_is_real_stereo and side_channel is not None:
        n = min(len(audio_data), len(side_channel))
        audio_data = audio_data[:n]
        side_channel = side_channel[:n]

        left = (audio_data + side_channel).astype(np.float32)
        right = (audio_data - side_channel).astype(np.float32)
        peak = float(np.max(np.abs(np.stack([left, right])))) + 1e-9
        if peak > 0.95:
            left = (left / peak * 0.95).astype(np.float32)
            right = (right / peak * 0.95).astype(np.float32)
        return np.stack([left, right], axis=1)

    elif is_stereo:
        peak = float(np.max(np.abs(audio_data))) + 1e-9
        if peak > 0.95:
            audio_data = (audio_data / peak * 0.95).astype(np.float32)
        return np.stack([audio_data, audio_data], axis=1)

    else:
        peak = float(np.max(np.abs(audio_data))) + 1e-9
        if peak > 0.95:
            audio_data = (audio_data / peak * 0.95).astype(np.float32)
        return audio_data


def save_output(output_path, final_output, is_stereo=False):
    final_output = np.clip(final_output, -1.0, 1.0)
    sf.write(str(output_path), final_output, SAMPLE_RATE)
    print(f"PROGRESS: done stereo={is_stereo}", flush=True)