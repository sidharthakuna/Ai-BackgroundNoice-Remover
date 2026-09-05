"""
keepalive.py — Self-pinging keep-alive background service for Render Free Tier.
Sends periodic HTTP GET requests to RENDER_EXTERNAL_URL/health every 12 minutes
to prevent Render from spinning down due to inactivity.
"""

import asyncio
import urllib.request
from app.config import KEEPALIVE_ENABLED, RENDER_EXTERNAL_URL, KEEPALIVE_INTERVAL_SECONDS


async def keepalive_loop():
    if not KEEPALIVE_ENABLED:
        return

    url = RENDER_EXTERNAL_URL.strip()
    if not url:
        return

    target = f"{url.rstrip('/')}/health"
    print(f"[keepalive] Service enabled for {target} (interval: {KEEPALIVE_INTERVAL_SECONDS}s)", flush=True)

    # Initial delay before first ping
    await asyncio.sleep(60)

    while True:
        try:
            await asyncio.to_thread(_ping, target)
        except Exception as e:
            print(f"[keepalive] Self-ping warning: {e}", flush=True)
        await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)


def _ping(target: str):
    req = urllib.request.Request(target, headers={"User-Agent": "AudioDenoise-KeepAlive/2.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status == 200:
            print(f"[keepalive] Ping to {target} -> 200 OK", flush=True)
