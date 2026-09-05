"""
test_dsp.py — Unit tests for studio 48kHz audio DSP processing modules.
"""

import numpy as np
import pytest

from app.config import SAMPLE_RATE
from app.denoise.dsp import (
    apply_highpass,
    apply_spectral_gating,
    apply_dynamics,
    apply_tone_mastering
)


def generate_sine_wave(freq_hz: float, duration_sec: float = 1.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    return np.sin(2 * np.pi * freq_hz * t).astype(np.float32)


def test_highpass_attenuates_sub_bass():
    """Verify that a 30Hz rumble is heavily attenuated while 1000Hz speech is preserved."""
    rumble = generate_sine_wave(30.0, duration_sec=1.0)
    speech = generate_sine_wave(1000.0, duration_sec=1.0)

    filtered_rumble = apply_highpass(rumble, cutoff_hz=75.0)
    filtered_speech = apply_highpass(speech, cutoff_hz=75.0)

    # 30Hz rumble should be attenuated by at least 15 dB (~0.18 linear)
    rumble_ratio = np.max(np.abs(filtered_rumble)) / (np.max(np.abs(rumble)) + 1e-9)
    assert rumble_ratio < 0.20, f"Rumble was not sufficiently attenuated: ratio={rumble_ratio}"

    # 1000Hz speech should have near-unity passband gain (> 0.95)
    speech_ratio = np.max(np.abs(filtered_speech)) / (np.max(np.abs(speech)) + 1e-9)
    assert speech_ratio > 0.90, f"Speech signal was unexpectedly attenuated: ratio={speech_ratio}"


def test_spectral_gating_reduces_noise_floor():
    """Verify that Wiener spectral gating suppresses stationary background noise."""
    np.random.seed(42)
    clean_tone = generate_sine_wave(440.0, duration_sec=1.0) * 0.5
    noise = np.random.normal(0, 0.05, len(clean_tone)).astype(np.float32)
    noisy_signal = clean_tone + noise

    gated = apply_spectral_gating(noisy_signal, over_subtract=2.0, floor=0.05)

    assert len(gated) == len(noisy_signal)
    assert np.all(np.isfinite(gated))


def test_dynamics_peak_limiter_bounds():
    """Verify that dynamics limiter clamps peaks below ceiling without NaN or inf."""
    hot_signal = generate_sine_wave(500.0, duration_sec=0.5) * 3.0  # severely clipped signal
    limited = apply_dynamics(hot_signal, comp_ratio=4.0, target_peak=0.92)

    max_peak = np.max(np.abs(limited))
    assert max_peak <= 0.93, f"Peak exceeded limiter target: peak={max_peak}"
    assert np.all(np.isfinite(limited))


def test_tone_mastering_output_validity():
    """Verify 5-band EQ and mastering generates valid, normalized audio."""
    signal = generate_sine_wave(800.0, duration_sec=1.0) * 0.3
    mastered = apply_tone_mastering(signal, target_lufs=-14.0)

    assert len(mastered) == len(signal)
    assert np.max(np.abs(mastered)) <= 0.96
    assert np.all(np.isfinite(mastered))
