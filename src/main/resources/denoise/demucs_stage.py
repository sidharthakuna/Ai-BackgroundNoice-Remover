"""
demucs_stage.py — optional Demucs vocal source separation (original
Stage 9).

Kept in its own file because it's the only stage that's conditional
(--demucs flag), spawns an external subprocess, and round-trips through
temp files on disk instead of operating on the in-memory array like
every other stage. None of the other modules in this package do any of
those three things.

EDIT THIS FILE IF you need to change:
  - Which Demucs model/stem separation is used (currently htdemucs,
    two-stems=vocals)
  - Temp file handling / cleanup

This stage runs AFTER dynamics.py (compressor/limiter) and BEFORE
tone.py's LUFS normalization in main.py's pipeline order, so whatever
Demucs returns still gets loudness-normalized afterward.
"""

import os
import sys
import subprocess
import tempfile
import shutil
import numpy as np
import librosa
import soundfile as sf

SAMPLE_RATE = 16000

# Demucs spawns a second, fully independent Python process that loads its own
# copy of PyTorch plus the htdemucs model -- on top of whatever the parent
# process (which already has DeepFilterNet loaded) is using. On a tightly
# constrained container (e.g. Render's free 512MB tier) that stacked cost can
# exceed what's left, and the OS OOM-killer gives no useful error of its own --
# the subprocess just disappears with exit code -9. Checking available memory
# first turns that into an actionable message instead of a silent kill.
MIN_AVAILABLE_MB_FOR_DEMUCS = 220


def _available_memory_mb():
    """Best-effort read of MemAvailable from /proc/meminfo (Linux containers
    only). Returns None if unavailable (e.g. non-Linux dev machine) so the
    caller can skip the check rather than block on a platform it can't read."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / 1024
    except Exception:
        pass
    return None


def apply_demucs_separation(audio_data, timeout_seconds=600):
    """Writes audio_data to a temp WAV, runs Demucs two-stem vocal
    separation via subprocess, reloads the isolated vocals track, and
    cleans up temp files. Raises if the subprocess fails, times out, or
    the container doesn't have enough free memory to safely attempt it
    (caught by main.py's error wrapper)."""
    available_mb = _available_memory_mb()
    if available_mb is not None and available_mb < MIN_AVAILABLE_MB_FOR_DEMUCS:
        raise RuntimeError(
            f"Not enough free memory for Demucs vocal isolation "
            f"({available_mb:.0f}MB available, {MIN_AVAILABLE_MB_FOR_DEMUCS}MB required). "
            f"Try again without the Demucs option, or on a longer/quieter clip so "
            f"less of the pipeline's memory is already in use."
        )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    sf.write(tmp, audio_data, SAMPLE_RATE)
    try:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "demucs.separate", "--two-stems=vocals",
                 "-o", os.path.dirname(tmp), tmp],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Demucs vocal isolation timed out after {timeout_seconds} seconds. "
                f"Try again without the Demucs option, or with a shorter clip."
            )
        if proc.returncode != 0:
            if proc.returncode < 0:
                # Negative returncode from subprocess.run means the child was
                # killed by that signal number (e.g. -9 = SIGKILL, the OOM
                # killer's signature). The memory check above should catch
                # most of these before they happen, but if the container's
                # available memory changed after that check ran (e.g. another
                # job started), this still gives an accurate message instead
                # of a raw "Demucs vocal separation process failed".
                raise RuntimeError(
                    f"Demucs vocal isolation was terminated (signal {-proc.returncode}), "
                    f"likely because the container ran out of memory. Try again without "
                    f"the Demucs option, or with a shorter clip."
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