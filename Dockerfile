# ============================================================================
# AI Background Noise Remover — Production Container (Render Free Tier 512MB)
# Ultra-lean Python 3.11-slim runtime with pre-warmed DeepFilterNet3 & Demucs
# ============================================================================

FROM python:3.11-slim

# Prevent thread pool thrashing on container CPU quotas
ENV OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    TORCH_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Install FFmpeg, libsndfile, git, curl, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install PyTorch CPU-only first for layer caching efficiency
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    torch==2.1.2 \
    torchaudio==2.1.2 \
    --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# 2. Pre-download neural weights into container image cache
COPY scripts/ /app/scripts/
RUN python3 scripts/warmup_models.py

# 3. Copy backend application and frontend static files
COPY app/ /app/app/
COPY static/ /app/static/

EXPOSE 8080

# Starts single-worker Uvicorn: binds directly to $PORT dynamically assigned by Render
CMD ["sh", "-c", "exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]