"""
job_models.py — Data structures and Pydantic schemas for audio jobs.
"""

from enum import Enum
from typing import Optional, List, Callable, Any
from datetime import datetime, timezone
import time
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    DENOISING = "DENOISING"
    CONVERTING = "CONVERTING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobAcceptedResponse(BaseModel):
    jobId: str
    statusUrl: str


class JobStatusResponse(BaseModel):
    jobId: str
    status: JobStatus
    message: str
    progressPercentage: int
    resultReady: bool
    errorMessage: Optional[str] = None
    originalFilename: str
    mode: str
    format: str
    processingTimeMs: int
    queuePosition: int = 0
    audioDurationSeconds: Optional[float] = None
    channels: Optional[int] = None
    sampleRate: Optional[int] = None


class JobRecord:
    """Internal mutable state for a single audio processing job."""

    def __init__(self, job_id: str, original_filename: str):
        self.job_id: str = job_id
        self.original_filename: str = original_filename
        self.created_at: float = time.time()
        self.status: JobStatus = JobStatus.QUEUED
        self.progress_message: str = "Queued"
        self.progress_percentage: int = 5
        self.job_dir: Optional[str] = None
        self.output_path: Optional[str] = None
        self.output_content_type: str = "audio/wav"
        self.error_message: Optional[str] = None
        self.error_status: int = 500

        self.mode: str = "balanced"
        self.use_demucs: bool = False
        self.output_format: str = "wav"
        self.file_size_bytes: int = 0
        self.processing_time_ms: int = 0
        self.finished_at: Optional[float] = None

        self.queue_position: int = 0
        self.audio_duration_seconds: Optional[float] = None
        self.sample_rate: Optional[int] = None
        self.channels: Optional[int] = None

        self.is_cancelled: bool = False
        self._listeners: List[Callable[["JobRecord"], None]] = []

    def add_listener(self, listener: Callable[["JobRecord"], None]) -> None:
        self._listeners.append(listener)
        try:
            listener(self)
        except Exception:
            pass

    def remove_listener(self, listener: Callable[["JobRecord"], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self) -> None:
        for l in list(self._listeners):
            try:
                l(self)
            except Exception:
                pass

    def mark_progress(self, status: JobStatus, message: str, progress: Optional[int] = None) -> None:
        self.status = status
        self.progress_message = message
        if progress is not None:
            self.progress_percentage = max(0, min(100, progress))
        self._notify()

    def mark_done(self, output_path: str, content_type: str) -> None:
        self.output_path = output_path
        self.output_content_type = content_type
        self.status = JobStatus.DONE
        self.progress_message = "Complete"
        self.progress_percentage = 100
        self.finished_at = time.time()
        self.processing_time_ms = int((self.finished_at - self.created_at) * 1000)
        self.queue_position = 0
        self._notify()

    def mark_failed(self, error_message: str, error_status: int = 500) -> None:
        self.error_message = error_message
        self.error_status = error_status
        self.status = JobStatus.FAILED
        self.progress_message = "Failed"
        self.finished_at = time.time()
        self.queue_position = 0
        self._notify()

    def to_response(self) -> JobStatusResponse:
        return JobStatusResponse(
            jobId=self.job_id,
            status=self.status,
            message=self.progress_message,
            progressPercentage=self.progress_percentage,
            resultReady=(self.status == JobStatus.DONE),
            errorMessage=self.error_message if self.status == JobStatus.FAILED else None,
            originalFilename=self.original_filename,
            mode=self.mode,
            format=self.output_format,
            processingTimeMs=self.processing_time_ms,
            queuePosition=self.queue_position,
            audioDurationSeconds=self.audio_duration_seconds,
            channels=self.channels,
            sampleRate=self.sample_rate
        )
