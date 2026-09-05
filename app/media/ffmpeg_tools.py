"""
ffmpeg_tools.py — Robust FFmpeg audio extraction, format conversion, and metadata probing.
"""

import os
import subprocess
from typing import Tuple, Optional
from app.config import SAMPLE_RATE


def extract_audio_from_video(video_path: str, output_wav_path: str) -> None:
    """Extracts the audio track from a video container into a 48kHz 16-bit PCM WAV."""
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", video_path,
        "-vn",
        "-ar", str(SAMPLE_RATE),
        "-acodec", "pcm_s16le",
        "-loglevel", "error",
        output_wav_path
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        err = e.stderr or ""
        if "does not contain any stream" in err.lower() or "output file is empty" in err.lower():
            raise ValueError("This video file does not appear to contain an audio track.")
        raise RuntimeError(f"FFmpeg audio extraction failed: {err}")

    if not os.path.exists(output_wav_path) or os.path.getsize(output_wav_path) == 0:
        raise ValueError("The extracted audio track was empty.")


def convert_audio_format(input_wav_path: str, output_path: str, target_format: str) -> None:
    """Converts a master WAV file into the requested target format (mp3, flac, ogg, m4a, aac)."""
    target = target_format.lower()
    if target == "wav":
        if input_wav_path != output_path:
            import shutil
            shutil.copy2(input_wav_path, output_path)
        return

    cmd = ["ffmpeg", "-nostdin", "-y", "-i", input_wav_path]

    if target == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", "320k"])
    elif target == "flac":
        cmd.extend(["-c:a", "flac"])
    elif target == "ogg":
        cmd.extend(["-c:a", "libvorbis", "-q:a", "6"])
    elif target in ("m4a", "aac"):
        cmd.extend(["-c:a", "aac", "-b:a", "256k"])
    else:
        cmd.extend(["-c:a", "copy"])

    cmd.extend(["-loglevel", "error", output_path])
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg format conversion to .{target} failed: {e.stderr}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Conversion to .{target} produced an empty file.")


def probe_audio(audio_path: str) -> Tuple[Optional[float], Optional[int], Optional[int]]:
    """
    Probes audio duration (seconds), sample rate (Hz), and channel count using soundfile/scipy.
    Returns (duration_seconds, sample_rate, channels).
    """
    try:
        import soundfile as sf
        info = sf.info(audio_path)
        return round(info.duration, 2), info.samplerate, info.channels
    except Exception:
        pass

    try:
        # Fallback to ffprobe if available
        import json
        cmd = [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=sample_rate,channels",
            "-of", "json", audio_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        duration = float(data.get("format", {}).get("duration", 0.0))
        streams = data.get("streams", [])
        sr = int(streams[0].get("sample_rate", SAMPLE_RATE)) if streams else SAMPLE_RATE
        channels = int(streams[0].get("channels", 1)) if streams else 1
        return round(duration, 2), sr, channels
    except Exception:
        return None, None, None
