"""
config.py — Global configuration and presets for the AI Noise Remover backend.
"""

import os
from typing import Dict, Any, Set

PORT: int = int(os.environ.get("PORT", 8080))
SAMPLE_RATE: int = 48000
MAX_UPLOAD_SIZE_BYTES: int = 100 * 1024 * 1024  # 100MB

ALLOWED_AUDIO_EXTENSIONS: Set[str] = {"wav", "mp3", "flac", "ogg", "m4a", "aac"}
ALLOWED_VIDEO_EXTENSIONS: Set[str] = {"mp4", "mov", "mkv", "webm"}
ALL_ALLOWED_EXTENSIONS: Set[str] = ALLOWED_AUDIO_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS
ALLOWED_OUTPUT_FORMATS: Set[str] = {"wav", "mp3", "flac", "ogg", "m4a", "aac"}

# DSP Tuning Modes
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

# Long audio streaming chunking parameters (keeps RAM strictly bounded on Render 512MB)
CHUNK_THRESHOLD_SECONDS: float = 60.0
STREAM_CHUNK_SECONDS: float = 30.0
STREAM_OVERLAP_SECONDS: float = 1.0

# Memory warning threshold for Render Free Tier (512MB RAM)
MEMORY_WARNING_MB: float = 400.0

# Keep-alive settings for Render Free Tier (prevents 15-minute sleep)
KEEPALIVE_ENABLED: bool = os.environ.get("APP_KEEPALIVE_ENABLED", "true").lower() in ("true", "1", "yes")
RENDER_EXTERNAL_URL: str = os.environ.get("RENDER_EXTERNAL_URL", "")
KEEPALIVE_INTERVAL_SECONDS: int = 720  # 12 minutes

# Job retention in hours
JOB_RETENTION_HOURS: int = 2
