"""
main.py — Main FastAPI entrypoint for the AI Background Noise Remover backend.
Serves static frontend, API endpoints, handles lifespan pre-warming, and runs keepalive.
"""

import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import PORT
from app.api import router_audio, router_jobs, router_health
from app.denoise.engine import model_registry
from app.denoise.memory_guard import memory_guard
from app.core.job_queue import job_queue
from app.core.job_store import job_store
from app.core.keepalive import keepalive_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[main] Starting AI Background Noise Remover (FastAPI Engine)...", flush=True)

    # 1. Pre-warm DeepFilterNet3 neural models in RAM
    model_registry.preload_models()

    # 2. Start single-worker concurrency queue
    job_queue.start()

    # 3. Start periodic job store eviction task
    async def eviction_task():
        while True:
            await asyncio.sleep(600)  # Every 10 minutes
            evicted = job_store.evict_expired()
            if evicted > 0:
                print(f"[job_store] Evicted {evicted} expired jobs.", flush=True)

    eviction_handle = asyncio.create_task(eviction_task())

    # 4. Start keepalive loop for Render
    keepalive_handle = asyncio.create_task(keepalive_loop())

    yield

    # Shutdown
    eviction_handle.cancel()
    keepalive_handle.cancel()
    memory_guard.cleanup()
    print("[main] All services stopped cleanly.", flush=True)


app = FastAPI(
    title="AI Background Noise Remover",
    description="Studio-grade AI audio noise removal, dynamic speech leveling, and vocal isolation.",
    version="3.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers FIRST so they take precedence over static file routes
app.include_router(router_audio)
app.include_router(router_jobs)
app.include_router(router_health)


# Favicon handler
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"message": f"Internal server error: {str(exc)}"}
    )


# Mount static frontend at root
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, workers=1, log_level="info")
