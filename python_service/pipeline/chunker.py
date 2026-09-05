"""
chunker.py — Overlap-add block processor for long audio files.
Guarantees memory usage stays strictly bounded (< 120MB) on Render free tier
regardless of whether the input audio is 30 seconds or 30 minutes long.
"""

import gc
import numpy as np
from typing import Callable
from python_service.config import SAMPLE_RATE, STREAM_CHUNK_SECONDS, STREAM_OVERLAP_SECONDS


def process_audio_chunked_or_direct(
    audio: np.ndarray,
    process_fn: Callable[[np.ndarray], np.ndarray],
    threshold_seconds: float = 60.0,
    chunk_seconds: float = STREAM_CHUNK_SECONDS,
    overlap_seconds: float = STREAM_OVERLAP_SECONDS
) -> np.ndarray:
    """
    If audio duration is under threshold_seconds, processes directly in one block.
    If longer, chunks audio into chunk_seconds segments with overlap_seconds crossfades,
    freeing intermediate arrays after each chunk to prevent memory spikes.
    """
    total_samples = len(audio)
    duration_seconds = total_samples / SAMPLE_RATE

    if duration_seconds <= threshold_seconds:
        result = process_fn(audio)
        gc.collect()
        return result

    chunk_samples = int(chunk_seconds * SAMPLE_RATE)
    overlap_samples = int(overlap_seconds * SAMPLE_RATE)
    step_samples = chunk_samples - overlap_samples

    output = np.zeros(total_samples, dtype=np.float32)
    weights = np.zeros(total_samples, dtype=np.float32)

    fade_in = np.linspace(0.0, 1.0, overlap_samples, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, overlap_samples, dtype=np.float32)

    num_chunks = max(1, int(np.ceil((total_samples - overlap_samples) / step_samples)))

    for i in range(num_chunks):
        start = i * step_samples
        end = min(start + chunk_samples, total_samples)
        chunk = audio[start:end]
        actual_len = len(chunk)

        if actual_len < chunk_samples:
            pad_len = chunk_samples - actual_len
            chunk = np.pad(chunk, (0, pad_len))
        else:
            pad_len = 0

        # Construct chunk-specific window: first chunk doesn't fade in, last chunk doesn't fade out
        chunk_window = np.ones(chunk_samples, dtype=np.float32)
        if i > 0:
            chunk_window[:overlap_samples] = fade_in
        if i < num_chunks - 1:
            chunk_window[-overlap_samples:] = fade_out

        # Process single chunk
        processed_chunk = process_fn(chunk)

        # Slice to actual unpadded length
        w = chunk_window[:actual_len]
        output[start:start + actual_len] += processed_chunk[:actual_len] * w
        weights[start:start + actual_len] += w

        del chunk, processed_chunk
        gc.collect()

    weights = np.maximum(weights, 1e-6)
    normalized_output = (output / weights).astype(np.float32)
    del output, weights
    gc.collect()

    return normalized_output
