"""
job_store.py — Thread-safe in-memory store for jobs with automatic file cleanup and TTL eviction.
"""

import os
import shutil
import time
import threading
from typing import Dict, Optional, List
from app.config import JOB_RETENTION_HOURS
from app.core.job_models import JobRecord, JobStatus


class JobStore:
    """Stores JobRecords in memory and manages disk cleanup."""

    def __init__(self, retention_hours: int = JOB_RETENTION_HOURS):
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self.retention_seconds = retention_hours * 3600

    def put(self, record: JobRecord) -> None:
        with self._lock:
            self._jobs[record.job_id] = record

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def remove(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            record = self._jobs.pop(job_id, None)
        if record:
            self.cleanup_job_dir(record)
        return record

    def list_all(self) -> List[JobRecord]:
        with self._lock:
            return list(self._jobs.values())

    def cleanup_job_dir(self, record: JobRecord) -> None:
        """Deletes job directory safely."""
        if record.job_dir and os.path.exists(record.job_dir):
            try:
                shutil.rmtree(record.job_dir, ignore_errors=True)
            except Exception:
                pass

    def evict_expired(self) -> int:
        """Removes jobs older than retention period."""
        now = time.time()
        to_evict = []
        with self._lock:
            for job_id, record in self._jobs.items():
                if now - record.created_at > self.retention_seconds:
                    to_evict.append(job_id)

        count = 0
        for job_id in to_evict:
            if self.remove(job_id):
                count += 1
        return count

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            active = sum(1 for j in self._jobs.values() if j.status in (JobStatus.QUEUED, JobStatus.EXTRACTING, JobStatus.DENOISING, JobStatus.CONVERTING))
            completed = sum(1 for j in self._jobs.values() if j.status == JobStatus.DONE)
            failed = sum(1 for j in self._jobs.values() if j.status in (JobStatus.FAILED, JobStatus.CANCELLED))
            return {
                "active": active,
                "completed": completed,
                "failed": failed,
                "total": len(self._jobs)
            }


job_store = JobStore()
