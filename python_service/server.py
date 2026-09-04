"""
server.py — FastAPI microservice for AI background noise removal.
Listens on internal 127.0.0.1:5000.
Streams real-time DSP progress events to Java backend via NDJSON.
"""

import asyncio
import json
import traceback
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

from python_service.engine import model_manager
from python_service.pipeline import execute_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm neural models during container start
    model_manager.preload_models()
    yield
    # Cleanup memory on shutdown
    model_manager.cleanup_memory()


app = FastAPI(
    title="AI Background Noise Remover Microservice",
    version="2.0.0",
    lifespan=lifespan
)


class ProcessRequest(BaseModel):
    job_id: str
    input_path: str
    output_path: str
    mode: Optional[str] = "balanced"
    use_demucs: Optional[bool] = False


@app.get("/health")
def health():
    """Health check endpoint queried by Java Backend."""
    mem_info = model_manager.get_memory_info()
    return {
        "status": "UP",
        "service": "ai-noise-remover-python",
        "memory": mem_info
    }


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Sets cooperative cancellation token for active job."""
    success = model_manager.cancel_job(job_id)
    return {
        "job_id": job_id,
        "cancelled": success
    }


@app.post("/process")
async def process_audio(req: ProcessRequest):
    """
    Executes DSP enhancement pipeline and streams newline-delimited JSON
    progress events back to Java in real time.
    """
    model_manager.register_job(req.job_id)
    event_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def sync_progress_callback(pct: int, stage: str, msg: str):
        event = {
            "job_id": req.job_id,
            "progress": pct,
            "stage": stage,
            "message": msg,
            "status": "DONE" if pct == 100 else "RUNNING"
        }
        loop.call_soon_threadsafe(event_queue.put_nowait, event)

    def cancel_check() -> bool:
        return model_manager.is_cancelled(req.job_id)

    async def run_in_background():
        try:
            success = await asyncio.to_thread(
                execute_pipeline,
                req.input_path,
                req.output_path,
                req.mode or "balanced",
                req.use_demucs or False,
                model_manager,
                sync_progress_callback,
                cancel_check
            )
            if not success:
                # Cancelled
                event = {
                    "job_id": req.job_id,
                    "progress": 0,
                    "stage": "CANCELLED",
                    "message": "Job was cancelled",
                    "status": "CANCELLED"
                }
                await event_queue.put(event)
        except Exception as exc:
            traceback.print_exc()
            event = {
                "job_id": req.job_id,
                "progress": 0,
                "stage": "FAILED",
                "message": str(exc),
                "status": "FAILED"
            }
            await event_queue.put(event)
        finally:
            model_manager.unregister_job(req.job_id)
            model_manager.cleanup_memory()
            # Sentinel to close stream
            await event_queue.put(None)

    # Launch processing task
    asyncio.create_task(run_in_background())

    async def event_generator():
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


if __name__ == "__main__":
    uvicorn.run("python_service.server:app", host="127.0.0.1", port=5000, workers=1, log_level="info")
