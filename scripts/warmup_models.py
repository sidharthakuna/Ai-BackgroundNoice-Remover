"""
scripts/warmup_models.py — Pre-warm neural network weights during Docker build.
Caches DeepFilterNet3 and Demucs htdemucs models in the image layer so the container
starts instantly without runtime download latency on Render Free Tier.
"""

import sys
import types
from dataclasses import dataclass

# 1. Torchaudio backend compatibility shim for DeepFilterNet
@dataclass
class AudioMetaData:
    sample_rate: int = 48000
    num_frames: int = 0
    num_channels: int = 1
    bits_per_sample: int = 16
    encoding: str = "PCM_S"

try:
    import torchaudio
except ImportError:
    torchaudio = None

backend_mod = types.ModuleType("torchaudio.backend")
common_mod = types.ModuleType("torchaudio.backend.common")
common_mod.AudioMetaData = getattr(torchaudio, "AudioMetaData", AudioMetaData)
backend_mod.common = common_mod
sys.modules["torchaudio.backend"] = backend_mod
sys.modules["torchaudio.backend.common"] = common_mod
if torchaudio is not None:
    torchaudio.backend = backend_mod


def warmup_deepfilternet() -> None:
    print("[warmup] Pre-downloading DeepFilterNet3 model weights...", flush=True)
    try:
        from df.enhance import init_df
        # Downloads model to cache directory (~/.cache/DeepFilterNet/DeepFilterNet3)
        init_df(post_filter=False)
        print("[warmup] DeepFilterNet3 cached successfully.", flush=True)
    except Exception as exc:
        print(f"[warmup] Notice: DeepFilterNet pre-download encountered: {exc}. Runtime will load on demand.", flush=True)


def warmup_demucs() -> None:
    print("[warmup] Pre-downloading Demucs htdemucs model weights...", flush=True)
    try:
        from demucs.pretrained import get_model
        get_model("htdemucs")
        print("[warmup] Demucs htdemucs cached successfully.", flush=True)
    except Exception as exc:
        print(f"[warmup] Notice: Demucs pre-download encountered: {exc}. Runtime will load on demand.", flush=True)


if __name__ == "__main__":
    warmup_deepfilternet()
    warmup_demucs()
    print("[warmup] Model cache warmup completed.", flush=True)
