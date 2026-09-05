"""
job_queue.py — Single-worker async FIFO concurrency queue for Render Free Tier (512MB RAM).
Guarantees exactly one heavy audio processing job runs at a time, preventing OOM crashes,
while updating waiting jobs with their exact position in line.
"""

import asyncio
from typing import Callable, Coroutine, Any, Dict, List, Optional
from app.core.job_models import JobRecord, JobStatus


class JobQueue:
    """Async single-worker FIFO concurrency manager."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._waiting_jobs: List[JobRecord] = []
        self._current_job_id: Optional[str] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def start(self):
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self):
        while True:
            try:
                record, handler = await self._queue.get()
                async with self._lock:
                    if record in self._waiting_jobs:
                        self._waiting_jobs.remove(record)
                    self._current_job_id = record.job_id
                    record.queue_position = 0
                    self._update_positions()

                if not record.is_cancelled:
                    try:
                        await handler()
                    except Exception as exc:
                        if record.status not in (JobStatus.DONE, JobStatus.FAILED):
                            record.mark_failed(f"Unexpected processing failure: {exc}", 500)

                async with self._lock:
                    self._current_job_id = None
                    self._update_positions()

                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[queue] Error in worker loop: {e}", flush=True)

    async def enqueue(self, record: JobRecord, handler: Callable[[], Coroutine[Any, Any, None]]):
        """Enqueues a job for processing."""
        self.start()
        async with self._lock:
            self._waiting_jobs.append(record)
            self._update_positions()
        await self._queue.put((record, handler))

    def _update_positions(self):
        for idx, rec in enumerate(self._waiting_jobs):
            rec.queue_position = idx + 1
            if rec.status == JobStatus.QUEUED:
                rec.mark_progress(JobStatus.QUEUED, f"Waiting in queue (position {rec.queue_position})")

    async def cancel_if_waiting(self, job_id: str) -> bool:
        async with self._lock:
            for rec in self._waiting_jobs:
                if rec.job_id == job_id:
                    rec.is_cancelled = True
                    rec.mark_failed("Job was cancelled while waiting in queue.", 408)
                    self._waiting_jobs.remove(rec)
                    self._update_positions()
                    return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        return {
            "queue_depth": len(self._waiting_jobs),
            "is_processing": self._current_job_id is not None,
            "running_job_id": self._current_job_id
        }


job_queue = JobQueue()
