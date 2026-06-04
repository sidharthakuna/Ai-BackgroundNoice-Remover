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

RUN apt-get update && apt-get install -y \
    openjdk-21-jdk \
    ffmpeg \
    libsndfile1 \
    curl \
    build-essential \
    git \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir \
        torch==2.1.0 \
        torchaudio==2.1.0 \
        --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY --from=builder /app/target/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]