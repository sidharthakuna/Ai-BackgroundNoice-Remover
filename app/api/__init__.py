"""
api package — REST and SSE endpoint routers.
"""

from app.api.routes_audio import router as router_audio
from app.api.routes_jobs import router as router_jobs
from app.api.routes_health import router as router_health

__all__ = ["router_audio", "router_jobs", "router_health"]
