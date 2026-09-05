"""
model_registry.py — Neural model registry and cooperative job cancellation manager.
Pre-warms DeepFilterNet3 in RAM to eliminate cold starts, lazy-loads Demucs,
and coordinates job cancellation tokens.
"""

import os
import sys
import types
import threading
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
import torch

# Limit internal OpenMP/PyTorch thread counts to avoid CPU starvation
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["TORCH_NUM_THREADS"] = "1"
torch.set_num_threads(1)
torch.set_grad_enabled(False)

# Torchaudio backend compatibility shim for DeepFilterNet
if "torchaudio.backend" not in sys.modules:
    try:
        @dataclass
        class AudioMetaData:
            sample_rate: int = 48000
            num_frames: int = 0
            num_channels: int = 1
            bits_per_sample: int = 16
            encoding: str = "PCM_S"

        backend_mod = types.ModuleType("torchaudio.backend")
        common_mod = types.ModuleType("torchaudio.backend.common")
        common_mod.AudioMetaData = getattr(sys.modules.get("torchaudio", None), "AudioMetaData", AudioMetaData)
        backend_mod.common = common_mod
        sys.modules["torchaudio.backend"] = backend_mod
        sys.modules["torchaudio.backend.common"] = common_mod
        if "torchaudio" in sys.modules:
            sys.modules["torchaudio"].backend = backend_mod
    except Exception:
        pass


class ModelRegistry:
    """Manages neural network weights lifecycle and cooperative cancellation tokens."""

    def __init__(self):
        self._df_model_standard = None
        self._df_state_standard = None
        self._df_model_postfilter = None
        self._df_state_postfilter = None
        self._demucs_model = None
        self._lock = threading.Lock()
        self._cancellation_tokens: Dict[str, bool] = {}

    def preload_models(self) -> None:
        """Pre-loads DeepFilterNet3 neural models at microservice startup."""
        print("[model_registry] Pre-warming DeepFilterNet3 neural models in RAM...", flush=True)
        try:
            from df.enhance import init_df
            # Standard model (post_filter=False)
            self._df_model_standard, self._df_state_standard, _ = init_df(post_filter=False)
            print("[model_registry] Standard DeepFilterNet3 model loaded successfully.", flush=True)

            # Post-filter model (post_filter=True)
            self._df_model_postfilter, self._df_state_postfilter, _ = init_df(post_filter=True)
            print("[model_registry] Post-filter DeepFilterNet3 model loaded successfully.", flush=True)
        except Exception as exc:
            print(f"[model_registry] Warning: Could not pre-warm DeepFilterNet models ({exc}). Will load on-demand.", flush=True)

    def get_deepfilternet_model(self, post_filter: bool = False) -> Tuple[Any, Any]:
        """Returns pre-warmed DeepFilterNet3 model and state."""
        with self._lock:
            if post_filter:
                if self._df_model_postfilter is None:
                    from df.enhance import init_df
                    self._df_model_postfilter, self._df_state_postfilter, _ = init_df(post_filter=True)
                return self._df_model_postfilter, self._df_state_postfilter
            else:
                if self._df_model_standard is None:
                    from df.enhance import init_df
                    self._df_model_standard, self._df_state_standard, _ = init_df(post_filter=False)
                return self._df_model_standard, self._df_state_standard

    def get_demucs_model(self) -> Any:
        """Lazy loads Demucs model only when requested to conserve base memory."""
        with self._lock:
            if self._demucs_model is None:
                print("[model_registry] Loading Demucs htdemucs model...", flush=True)
                from demucs.pretrained import get_model
                self._demucs_model = get_model("htdemucs")
                self._demucs_model.eval()
                print("[model_registry] Demucs model ready.", flush=True)
            return self._demucs_model

    def register_job(self, job_id: str) -> None:
        with self._lock:
            self._cancellation_tokens[job_id] = False

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._cancellation_tokens:
                self._cancellation_tokens[job_id] = True
                print(f"[model_registry] Cancellation token set for job {job_id}", flush=True)
                return True
            return False

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return self._cancellation_tokens.get(job_id, False)

    def unregister_job(self, job_id: str) -> None:
        with self._lock:
            self._cancellation_tokens.pop(job_id, None)

    def get_status(self) -> Dict[str, Any]:
        """Returns model residency status for /health diagnostics."""
        return {
            "dfn_standard_loaded": self._df_model_standard is not None,
            "dfn_postfilter_loaded": self._df_model_postfilter is not None,
            "demucs_loaded": self._demucs_model is not None,
            "active_cancellation_tokens": len(self._cancellation_tokens)
        }


model_registry = ModelRegistry()
