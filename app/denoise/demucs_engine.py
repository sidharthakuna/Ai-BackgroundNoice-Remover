"""
demucs_engine.py — Memory-safe chunked Demucs vocal isolation.
Processes audio in 4.0-second frames with Hanning crossfades to bound memory.
"""

import gc
import numpy as np
import torch
from app.config import SAMPLE_RATE


def apply_demucs_chunked(audio: np.ndarray, demucs_model, chunk_seconds: float = 4.0) -> np.ndarray:
    """Executes Demucs vocal isolation on CPU in 4-second chunks with overlap-add."""
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
            sources = apply_model(demucs_model, tensor_in, device="cpu", num_workers=0, progress=False)
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
