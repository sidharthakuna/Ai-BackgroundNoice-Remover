"""
demucs_stage.py — Demucs vocal source separation with strict memory safety for 512MB RAM containers.
"""

import os
import sys
import subprocess
import tempfile
import shutil
import numpy as np
import librosa
import soundfile as sf

SAMPLE_RATE = 48000
MIN_AVAILABLE_MB_FOR_DEMUCS = 180


def _available_memory_mb():
    """Read MemAvailable from /proc/meminfo on Linux containers."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return None


def apply_demucs_separation(audio_data, timeout_seconds=600):
    """Writes audio_data to a temp WAV, runs Demucs two-stem vocal separation, and reloads."""
    available_mb = _available_memory_mb()
    if available_mb is not None and available_mb < MIN_AVAILABLE_MB_FOR_DEMUCS:
        raise RuntimeError(
            f"Not enough free memory for Demucs vocal isolation "
            f"({available_mb:.0f}MB available, {MIN_AVAILABLE_MB_FOR_DEMUCS}MB required). "
            f"Try again without the Demucs option."
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    sf.write(tmp, audio_data, SAMPLE_RATE)
    try:
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "demucs.separate",
                    "--two-stems=vocals",
                    "--segment=4",
                    "-o", os.path.dirname(tmp),
                    tmp
                ],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Demucs vocal isolation timed out after {timeout_seconds} seconds. "
                f"Try again without Demucs vocal isolation."
            )
        if proc.returncode != 0:
            if proc.returncode < 0:
                raise RuntimeError(
                    f"Demucs vocal isolation was terminated (signal {-proc.returncode}), "
                    f"likely due to memory constraints. Try again without Demucs."
                )
            err_msg = proc.stderr.strip() if proc.stderr else "Demucs vocal separation process failed"
            first_err_line = err_msg.splitlines()[-1] if err_msg else "Unknown error"
            raise RuntimeError(f"Demucs vocal isolation failed: {first_err_line}")

        vocals = os.path.join(
            os.path.dirname(tmp), "htdemucs",
            os.path.splitext(os.path.basename(tmp))[0], "vocals.wav"
        )
        if not os.path.exists(vocals):
            raise FileNotFoundError("Demucs finished but vocals output stem was not generated.")

        result, _ = librosa.load(vocals, sr=SAMPLE_RATE, mono=True)
        return result.astype(np.float32)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        shutil.rmtree(os.path.join(os.path.dirname(tmp), "htdemucs"), ignore_errors=True)