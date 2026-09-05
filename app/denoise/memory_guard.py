"""
memory_guard.py — Memory supervisor for Render Free Tier (512MB RAM constraint).
Monitors resident memory (VmRSS) and enforces proactive garbage reclamation.
"""

import gc
import os
from typing import Dict, Any
from app.config import MEMORY_WARNING_MB


class MemoryGuard:
    def __init__(self, warning_threshold_mb: float = MEMORY_WARNING_MB):
        self.warning_threshold_mb = warning_threshold_mb

    def get_rss_mb(self) -> float:
        """Returns the current process Resident Set Size (RSS) in megabytes."""
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
        rss = self.get_rss_mb()
        return {
            "rss_mb": rss,
            "warning_threshold_mb": self.warning_threshold_mb,
            "memory_pressure": rss > self.warning_threshold_mb
        }


memory_guard = MemoryGuard()
