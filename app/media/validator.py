"""
validator.py — Upload validation, filename sanitization, and parameter normalization.
"""

import os
import re
from fastapi import HTTPException
from app.config import (
    ALL_ALLOWED_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    ALLOWED_OUTPUT_FORMATS,
    MODE_CONFIGS
)


def sanitize_filename(filename: str) -> str:
    if not filename:
        return "unnamed_audio"
    # Remove directory traversals and special characters
    base = os.path.basename(filename)
    clean = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    return clean[:128] if clean else "unnamed_audio"


def extract_extension(filename: str) -> str:
    clean = sanitize_filename(filename)
    if "." not in clean:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file has no file extension."
        )
    ext = clean.rsplit(".", 1)[-1].lower()
    if ext not in ALL_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '.{ext}'. Supported formats: {', '.join(sorted(ALL_ALLOWED_EXTENSIONS))}."
        )
    return ext


def is_video_extension(ext: str) -> bool:
    return ext.lower() in ALLOWED_VIDEO_EXTENSIONS


def normalize_mode(mode: str) -> str:
    if not mode:
        return "balanced"
    m = mode.strip().lower()
    if m not in MODE_CONFIGS:
        return "balanced"
    return m


def normalize_output_format(fmt: str) -> str:
    if not fmt:
        return "wav"
    f = fmt.strip().lower()
    if f not in ALLOWED_OUTPUT_FORMATS:
        return "wav"
    return f
