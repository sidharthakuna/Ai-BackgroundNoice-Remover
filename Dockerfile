# ============================================================================
# Stage 1: Build Java Application with Maven
# ============================================================================

FROM eclipse-temurin:21-jdk AS builder

WORKDIR /app

COPY . .

RUN chmod +x mvnw
RUN ./mvnw clean package -DskipTests


# ============================================================================
# Stage 2: Runtime Environment (Python 3.11-slim + Java 21 JRE + FFmpeg)
# ============================================================================

FROM python:3.11-slim

# Copy Java 21 runtime directly from builder stage
COPY --from=builder /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Prevent CPU thrashing on container CFS quotas (limits thread pools for PyTorch, OpenBLAS, MKL)
ENV OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    TORCH_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Install FFmpeg, libsndfile and native build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    build-essential \
    git \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Install PyTorch CPU-only first for maximum caching efficiency
COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir \
    torch==2.1.2 \
    torchaudio==2.1.2 \
    --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cargo /root/.rustup

# Pre-download DeepFilterNet3 neural weights into image cache
RUN python3 -c "\
import sys, types; \
AudioMetaData = type('AudioMetaData', (), {'sample_rate': 48000, 'num_frames': 0, 'num_channels': 1, 'bits_per_sample': 16, 'encoding': 'PCM_S'}); \
b = types.ModuleType('torchaudio.backend'); \
c = types.ModuleType('torchaudio.backend.common'); \
c.AudioMetaData = AudioMetaData; \
b.common = c; \
sys.modules['torchaudio.backend'] = b; \
sys.modules['torchaudio.backend.common'] = c; \
from df.enhance import init_df; \
init_df(post_filter=False); \
init_df(post_filter=True)"

# Pre-download Demucs htdemucs weights into image cache
RUN python3 -c "from demucs.pretrained import get_model; get_model('htdemucs')"

# Copy built Spring Boot application JAR
COPY --from=builder /app/target/*.jar app.jar

EXPOSE 8080

# Serial GC, 40MB max heap, low metaspace/thread stack so Spring Boot consumes <85MB, leaving >420MB for Python in 512MB RAM containers
ENTRYPOINT ["java", "-XX:+UseSerialGC", "-Xms20m", "-Xmx40m", "-XX:MaxMetaspaceSize=40m", "-XX:ReservedCodeCacheSize=20m", "-Xss256k", "-jar", "app.jar"]