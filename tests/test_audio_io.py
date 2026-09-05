"""
test_audio_io.py — Unit tests for audio I/O and Mid/Side stereo encoding/decoding.
"""

import os
import tempfile
import numpy as np
import pytest

from python_service.config import SAMPLE_RATE
from python_service.audio_io import encode_mid_side, decode_mid_side, save_audio, load_audio


def test_mid_side_encode_decode_identity():
    """Verify that decode(encode(stereo)) == stereo within float32 precision."""
    t = np.linspace(0, 0.5, int(SAMPLE_RATE * 0.5), endpoint=False)
    left = (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    right = (0.3 * np.cos(2 * np.pi * 600 * t)).astype(np.float32)
    stereo = np.vstack([left, right])

    mid, side = encode_mid_side(stereo)
    reconstructed = decode_mid_side(mid, side)

    np.testing.assert_allclose(reconstructed, stereo, rtol=1e-5, atol=1e-5)


def test_save_and_load_roundtrip():
    """Verify writing a 48kHz WAV to disk and reading it back preserves shape and data."""
    t = np.linspace(0, 0.2, int(SAMPLE_RATE * 0.2), endpoint=False)
    audio = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, "test_roundtrip.wav")
        save_audio(wav_path, audio, sr=SAMPLE_RATE)
        assert os.path.exists(wav_path)

        loaded, sr, is_stereo = load_audio(wav_path)
        assert sr == SAMPLE_RATE
        assert not is_stereo
        np.testing.assert_allclose(loaded, audio, rtol=1e-4, atol=1e-4)
