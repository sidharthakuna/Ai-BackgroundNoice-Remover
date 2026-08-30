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


def apply_demucs_separation(audio_data):
    """Writes audio_data to a temp WAV, runs Demucs two-stem vocal
    separation via subprocess, reloads the isolated vocals track, and
    cleans up temp files. Raises if the subprocess fails (caught by
    main.py's error wrapper)."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    sf.write(tmp, audio_data, SAMPLE_RATE)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "demucs.separate", "--two-stems=vocals",
             "-o", os.path.dirname(tmp), tmp],
            capture_output=True,
            text=True
        )
        if proc.returncode != 0:
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