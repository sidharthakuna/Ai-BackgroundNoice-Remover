"""
highpass.py — 4th-order Butterworth high-pass rumble filter.
Removes sub-bass DC offset, mechanical hum, and microphone handling thump.
"""

import numpy as np
from scipy.signal import butter, sosfiltfilt
from python_service.config import SAMPLE_RATE


def apply_highpass(audio: np.ndarray, cutoff_hz: float = 75.0) -> np.ndarray:
    """
    Removes sub-bass rumble below cutoff_hz using a 4th-order zero-phase Butterworth filter.
    Operates on 1D mono float32 numpy arrays.
    """
    if len(audio) < 100:
        return audio.astype(np.float32)

    nyquist = SAMPLE_RATE / 2.0
    normalized_cutoff = min(cutoff_hz / nyquist, 0.99)
    sos = butter(4, normalized_cutoff, btype="high", output="sos")
    return sosfiltfilt(sos, audio).astype(np.float32)
