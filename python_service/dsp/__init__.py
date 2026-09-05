"""
dsp package — Studio 48kHz audio digital signal processing algorithms.
"""

from python_service.dsp.highpass import apply_highpass
from python_service.dsp.spectral_gate import apply_spectral_gating
from python_service.dsp.vad import apply_vad_gating
from python_service.dsp.dynamics import apply_dynamics
from python_service.dsp.tone import apply_tone_mastering

__all__ = [
    "apply_highpass",
    "apply_spectral_gating",
    "apply_vad_gating",
    "apply_dynamics",
    "apply_tone_mastering"
]
