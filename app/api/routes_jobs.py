"""
routes_jobs.py — Status polling, result download, cancellation, and SSE event streaming.
"""

import os
import asyncio
import json
from fastapi import APIRouter, HTTPException, status, Response
from fastapi.responses import FileResponse, StreamingResponse

from app.core.job_models import JobStatus, JobStatusResponse
from app.core.job_store import job_store
from app.core.job_queue import job_queue
from app.denoise.engine import model_registry

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    """Returns the current status, progress, and metadata for a job."""
    record = job_store.get(job_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No job found with id '{job_id}'. It may have expired."
        )
    return record.to_response()


@router.get("/{job_id}/result")
def download_result(job_id: str):
    """Downloads the enhanced audio file once status is DONE."""
    record = job_store.get(job_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No job found with id '{job_id}'. It may have expired."
        )

    if record.status == JobStatus.FAILED:
        raise HTTPException(
            status_code=record.error_status,
            detail=record.error_message or "Job failed."
        )

    if record.status != JobStatus.DONE:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not finished yet (status: {record.status}). Poll /status first."
        )

    if not record.output_path or not os.path.exists(record.output_path):
        raise HTTPException(
            status_code=410,
            detail="The result file is no longer available. It may have expired."
        )

    # Construct download filename
    orig = record.original_filename
    dot_idx = orig.rfind(".")
    base_name = (orig[:dot_idx] if dot_idx > 0 else orig) + "_enhanced"
    ext = record.output_format
    download_filename = f"{base_name}.{ext}"

    return FileResponse(
        path=record.output_path,
        media_type=record.output_content_type,
        filename=download_filename,
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"'
        }
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_or_delete_job(job_id: str):
    """Cancels active or waiting job, cleans up disk storage, and removes from store."""
    record = job_store.get(job_id)
    if record:
        record.is_cancelled = True
        model_registry.cancel_job(job_id)
        await job_queue.cancel_if_waiting(job_id)

    job_store.remove(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{job_id}/events")
async def stream_job_events(job_id: str):
    """Server-Sent Events (SSE) streaming progress updates directly to the browser."""
    record = job_store.get(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found.")

    queue = asyncio.Queue()

    def listener(rec):
        try:
            queue.put_nowait(rec.to_response())
        except Exception:
            pass

    record.add_listener(listener)

    async def event_generator():
        try:
            while True:
                resp = await queue.get()
                event_data = f"event: progress\ndata: {json.dumps(resp.model_dump())}\n\n"
                yield event_data

                if resp.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
                    break
        finally:
            record.remove_listener(listener)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
