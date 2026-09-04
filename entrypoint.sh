#!/bin/bash
set -e

echo "========================================================"
echo " Starting AI Background Noise Remover Container"
echo " (Java 21 Spring Boot + Persistent Python AI Microservice)"
echo "========================================================"

# Trap shutdown signals to terminate both background and foreground services gracefully
cleanup() {
    echo "[entrypoint] Received termination signal. Gracefully shutting down services..."
    if [ -n "$JAVA_PID" ]; then
        kill -TERM "$JAVA_PID" 2>/dev/null || true
    fi
    if [ -n "$PYTHON_PID" ]; then
        kill -TERM "$PYTHON_PID" 2>/dev/null || true
    fi
    wait "$JAVA_PID" 2>/dev/null || true
    wait "$PYTHON_PID" 2>/dev/null || true
    echo "[entrypoint] All services stopped cleanly."
    exit 0
}

trap cleanup SIGTERM SIGINT

# 1. Start persistent Python AI Microservice (127.0.0.1:5000)
echo "[entrypoint] Starting Python AI Microservice on 127.0.0.1:5000..."
python3 -m python_service.server &
PYTHON_PID=$!

# 2. Wait for Python microservice to report /health UP
echo "[entrypoint] Waiting for neural models to pre-warm in RAM..."
for i in $(seq 1 40); do
    if curl -s http://127.0.0.1:5000/health | grep -q '"status":"UP"'; then
        echo "[entrypoint] Python AI Microservice is UP and ready in RAM!"
        break
    fi
    sleep 1
done

# 3. Start Java Spring Boot Application
# JVM Options tailored for 512MB container limit:
# - Serial GC consumes minimal memory
# - Metaspace capped at 112m (prevents previous 40m Metaspace crash)
# - Heap capped at 64m (plenty for REST metadata; audio is streamed to/from disk)
# - 256k stack size for lightweight virtual threads
echo "[entrypoint] Starting Spring Boot Backend on port ${PORT:-8080}..."
java -XX:+UseSerialGC \
     -Xms32m \
     -Xmx64m \
     -XX:MaxMetaspaceSize=112m \
     -XX:ReservedCodeCacheSize=32m \
     -Xss256k \
     -jar app.jar &
JAVA_PID=$!

# Wait for Java process to exit or signal received
wait "$JAVA_PID"
