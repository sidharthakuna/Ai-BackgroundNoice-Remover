"""
routes_health.py — Health check and runtime diagnostics endpoint.
"""

from datetime import datetime, timezone
from fastapi import APIRouter
from app.denoise.memory_guard import memory_guard
from app.denoise.engine import model_registry
from app.core.job_store import job_store
from app.core.job_queue import job_queue

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    """Returns application health and memory metrics for Render."""
    mem_status = memory_guard.get_status()
    models_status = model_registry.get_status()
    job_stats = job_store.get_stats()
    queue_stats = job_queue.get_stats()

    return {
        "status": "UP",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "memory": mem_status,
        "models": models_status,
        "jobs": job_stats,
        "queue": queue_stats
    }
