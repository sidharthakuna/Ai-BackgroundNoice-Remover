"""
routes_audio.py — POST /api/v1/audio/enhance endpoint.
Accepts multipart audio/video files, stages temp storage, and dispatches to concurrency queue.
"""

import os
import uuid
import tempfile
import asyncio
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from fastapi.responses import JSONResponse

from app.config import MAX_UPLOAD_SIZE_BYTES
from app.core.job_models import JobRecord, JobStatus, JobAcceptedResponse
from app.core.job_store import job_store
from app.core.job_queue import job_queue
from app.media.validator import (
    sanitize_filename,
    extract_extension,
    is_video_extension,
    normalize_mode,
    normalize_output_format
)
from app.media.ffmpeg_tools import extract_audio_from_video, convert_audio_format, probe_audio
from app.denoise.pipeline import execute_pipeline
from app.denoise.engine import model_registry
from app.denoise.memory_guard import memory_guard

router = APIRouter(prefix="/api/v1/audio", tags=["Audio"])

CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
    "aac": "audio/aac"
}


@router.post("/enhance", status_code=status.HTTP_202_ACCEPTED, response_model=JobAcceptedResponse)
async def enhance_audio(
    file: UploadFile = File(...),
    mode: str = Form("balanced"),
    demucs: str = Form("false"),
    format: str = Form("wav")
):
    """
    Accepts an audio/video file for background noise removal.
    Returns 202 Accepted with a jobId and statusUrl immediately.
    """
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file was uploaded.")

    clean_filename = sanitize_filename(file.filename)
    ext = extract_extension(clean_filename)
    norm_mode = normalize_mode(mode)
    norm_format = normalize_output_format(format)
    use_demucs = demucs.lower() in ("true", "1", "yes")

    job_id = uuid.uuid4().hex[:8]
    job_dir = tempfile.mkdtemp(prefix=f"noise-job-{job_id}-")
    uploaded_path = os.path.join(job_dir, f"input.{ext}")

    # Stream file to disk in 64KB chunks to keep memory flat
    bytes_written = 0
    try:
        with open(uploaded_path, "wb") as dst:
            while chunk := await file.read(64 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="The uploaded file exceeds the maximum allowed size of 100MB."
                    )
                dst.write(chunk)
    except HTTPException:
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except Exception as e:
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Failed to save uploaded file: {e}")

    if bytes_written == 0:
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    # Probe audio metadata
    duration_sec, sample_rate, channels = probe_audio(uploaded_path)

    # Initialize JobRecord
    record = JobRecord(job_id, clean_filename)
    record.job_dir = job_dir
    record.mode = norm_mode
    record.use_demucs = use_demucs
    record.output_format = norm_format
    record.file_size_bytes = bytes_written
    record.audio_duration_seconds = duration_sec
    record.sample_rate = sample_rate
    record.channels = channels

    job_store.put(record)

    # Define background job execution logic
    async def process_job():
        model_registry.register_job(job_id)
        is_video = is_video_extension(ext)
        denoise_in = uploaded_path
        master_wav = os.path.join(job_dir, "output.wav")

        try:
            # Stage 1: Extraction if video
            if is_video:
                record.mark_progress(JobStatus.EXTRACTING, "Extracting audio track from video", 15)
                extracted_wav = os.path.join(job_dir, "extracted.wav")
                await asyncio.to_thread(extract_audio_from_video, uploaded_path, extracted_wav)
                denoise_in = extracted_wav

            if record.is_cancelled:
                return

            # Stage 2: AI Denoise Pipeline
            record.mark_progress(JobStatus.DENOISING, "Processing with AI engine", 30)

            def sync_progress(pct: int, stage: str, msg: str):
                record.mark_progress(JobStatus.DENOISING, msg, pct)

            def check_cancel() -> bool:
                return record.is_cancelled or model_registry.is_cancelled(job_id)

            success = await asyncio.to_thread(
                execute_pipeline,
                denoise_in,
                master_wav,
                norm_mode,
                use_demucs,
                model_registry,
                sync_progress,
                check_cancel
            )

            if not success or check_cancel():
                record.mark_failed("Job was cancelled.", 408)
                return

            # Stage 3: Format Conversion if not WAV
            final_output = master_wav
            if norm_format != "wav":
                record.mark_progress(JobStatus.CONVERTING, f"Converting to .{norm_format}", 95)
                target_path = os.path.join(job_dir, f"output.{norm_format}")
                await asyncio.to_thread(convert_audio_format, master_wav, target_path, norm_format)
                final_output = target_path

            # Complete!
            content_type = CONTENT_TYPES.get(norm_format, "audio/wav")
            record.mark_done(final_output, content_type)

        except Exception as exc:
            record.mark_failed(str(exc), 422 if "audio" in str(exc).lower() else 500)
        finally:
            model_registry.unregister_job(job_id)
            memory_guard.cleanup()

    # Enqueue to concurrency manager
    await job_queue.enqueue(record, process_job)

    return JobAcceptedResponse(
        jobId=job_id,
        statusUrl=f"/api/v1/jobs/{job_id}/status"
    )
