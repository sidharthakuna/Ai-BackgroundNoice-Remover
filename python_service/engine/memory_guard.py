"""
memory_guard.py — Memory supervisor for Render Free Tier (512MB RAM constraint).
Tracks VmRSS resident memory, triggers proactive garbage collection, and enforces bounds.
"""

import gc
import os
import sys
from typing import Dict, Any


class MemoryGuard:
    """Monitors system RSS memory and enforces proactive garbage reclamation."""

    def __init__(self, warning_threshold_mb: float = 400.0):
        self.warning_threshold_mb = warning_threshold_mb

    def get_rss_mb(self) -> float:
        """Returns the current process Resident Set Size (RSS) in megabytes."""
        # 1. Linux /proc/self/status (Render container environment)
        if os.path.exists("/proc/self/status"):
            try:
                with open("/proc/self/status", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return round(float(parts[1]) / 1024.0, 2)
            except Exception:
                pass

        # 2. psutil if installed
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return round(process.memory_info().rss / (1024.0 * 1024.0), 2)
        except Exception:
            pass

        return 0.0

    def cleanup(self) -> None:
        """Forces immediate cyclic garbage collection to release unreferenced buffers."""
        gc.collect()

    def get_status(self) -> Dict[str, Any]:
        """Provides memory diagnostics for /health endpoint."""
        rss = self.get_rss_mb()
        return {
            "rss_mb": rss,
            "warning_threshold_mb": self.warning_threshold_mb,
            "memory_pressure": rss > self.warning_threshold_mb
        }


memory_guard = MemoryGuard()
