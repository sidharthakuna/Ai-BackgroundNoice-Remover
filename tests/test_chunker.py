"""
test_chunker.py — Unit tests for overlap-add block chunking for long audio processing.
"""

import numpy as np
import pytest

from python_service.config import SAMPLE_RATE
from python_service.pipeline.chunker import process_audio_chunked_or_direct


def test_chunker_preserves_length_and_continuity():
    """Verify that chunked block processing produces smooth continuous audio of exact length."""
    # 5 seconds of audio
    t = np.linspace(0, 5.0, int(SAMPLE_RATE * 5.0), endpoint=False)
    input_audio = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)

    # Simple gain function (multiply by 0.8)
    def simple_gain(blk: np.ndarray) -> np.ndarray:
        return (blk * 0.8).astype(np.float32)

    # Force chunking by setting threshold low (e.g. 1.0s) with 2.0s chunks and 0.5s overlap
    output = process_audio_chunked_or_direct(
        input_audio,
        simple_gain,
        threshold_seconds=1.0,
        chunk_seconds=2.0,
        overlap_seconds=0.5
    )

    assert len(output) == len(input_audio)
    expected = input_audio * 0.8
    # Assert smooth overlap-add matches expected output
    np.testing.assert_allclose(output, expected, rtol=1e-3, atol=1e-3)
