# ==========================
# Build Stage
# ==========================

FROM eclipse-temurin:21-jdk AS builder

WORKDIR /app

COPY . .

RUN chmod +x mvnw
RUN ./mvnw clean package -DskipTests


# ==========================
# Runtime Stage
# ==========================

FROM python:3.11-slim

# Copy Java 21 runtime directly from builder stage
COPY --from=builder /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Prevent CPU thrashing on cloud containers (limits thread pools for PyTorch, OpenBLAS, MKL)
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV VECLIB_MAXIMUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1
ENV TORCH_NUM_THREADS=1
ENV PYTHONUNBUFFERED=1

# Install FFmpeg, libsndfile and native build tools
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    curl \
    build-essential \
    git \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*

# Rust
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# ==========================
# Python dependencies
# ==========================

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir \
    torch==2.1.0 \
    torchaudio==2.1.0 \
    --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download DeepFilterNet pre-trained neural models so they are cached in the image
# This eliminates runtime download delay on cloud hosts like Render
RUN python3 -c "import sys, types; from dataclasses import dataclass; \
@dataclass \
class AudioMetaData: sample_rate: int = 16000; num_frames: int = 0; num_channels: int = 1; bits_per_sample: int = 16; encoding: str = 'PCM_S'; \
b = types.ModuleType('torchaudio.backend'); c = types.ModuleType('torchaudio.backend.common'); c.AudioMetaData = AudioMetaData; b.common = c; sys.modules['torchaudio.backend'] = b; sys.modules['torchaudio.backend.common'] = c; \
from df.enhance import init_df; init_df(post_filter=False); init_df(post_filter=True)"


# ==========================
# Application
# ==========================

COPY --from=builder /app/target/*.jar app.jar

EXPOSE 8080

# Use Serial GC, 48MB max heap, and low metaspace/thread stack so Spring Boot consumes <90MB, leaving >420MB free for Python & PyTorch in 512MB RAM containers
ENTRYPOINT ["java", "-XX:+UseSerialGC", "-Xms24m", "-Xmx48m", "-XX:MaxMetaspaceSize=48m", "-XX:ReservedCodeCacheSize=24m", "-Xss256k", "-jar", "app.jar"]