"""
config.py — Configuration profiles, DSP parameters, and memory thresholds for AI Noise Remover.
"""

from typing import Dict, Any

SAMPLE_RATE = 48000

# Preset DSP tuning profiles
MODE_CONFIGS: Dict[str, Dict[str, Any]] = {
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

# Threshold (in seconds) beyond which audio is processed via streaming chunks to protect 512MB RAM
CHUNK_STREAMING_THRESHOLD_SECONDS = 60.0

# Chunk duration in seconds for block processing
STREAM_CHUNK_SECONDS = 30.0

# Overlap duration in seconds for smooth crossfade
STREAM_OVERLAP_SECONDS = 1.0
