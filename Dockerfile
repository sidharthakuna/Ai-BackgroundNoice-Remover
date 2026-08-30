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
RUN python3 -c "from df.enhance import init_df; init_df(post_filter=False); init_df(post_filter=True)"


# ==========================
# Application
# ==========================

COPY --from=builder /app/target/*.jar app.jar

EXPOSE 8080

# Use Serial GC and tight memory limits so Spring Boot only uses ~150MB, leaving 350MB free for Python & PyTorch in 512MB RAM containers
ENTRYPOINT ["java", "-XX:+UseSerialGC", "-Xms64m", "-Xmx128m", "-XX:MaxMetaspaceSize=96m", "-XX:ReservedCodeCacheSize=48m", "-Xss512k", "-jar", "app.jar"]