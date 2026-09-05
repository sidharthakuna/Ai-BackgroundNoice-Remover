"""
test_api.py — Integration tests for FastAPI endpoints (REST, health, static files, and processing).
"""

import io
import time
import numpy as np
import pytest
from fastapi.testclient import TestClient
import soundfile as sf

from app.main import app
from app.config import SAMPLE_RATE


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def generate_wav_bytes(duration_sec: float = 0.5, freq: float = 440.0) -> bytes:
    t = np.linspace(0, duration_sec, int(SAMPLE_RATE * duration_sec), endpoint=False)
    audio = (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "UP"
    assert "memory" in data
    assert "jobs" in data
    assert "queue" in data


def test_root_serves_index_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "<title>" in resp.text


def test_enhance_rejects_empty_file(client):
    files = {"file": ("empty.wav", b"", "audio/wav")}
    resp = client.post("/api/v1/audio/enhance", files=files)
    assert resp.status_code == 400


def test_enhance_rejects_invalid_extension(client):
    files = {"file": ("document.pdf", b"fake content", "application/pdf")}
    resp = client.post("/api/v1/audio/enhance", files=files)
    assert resp.status_code == 400
    assert "Unsupported file format" in resp.json()["detail"]


def test_enhance_and_polling_lifecycle(client):
    wav_bytes = generate_wav_bytes(duration_sec=0.2)
    files = {"file": ("sample.wav", wav_bytes, "audio/wav")}
    data = {"mode": "balanced", "demucs": "false", "format": "wav"}

    # 1. POST enhance -> 202
    resp = client.post("/api/v1/audio/enhance", files=files, data=data)
    assert resp.status_code == 202
    job_info = resp.json()
    job_id = job_info["jobId"]
    assert "statusUrl" in job_info

    # 2. Poll until DONE or timeout
    max_wait = 30
    start = time.time()
    done = False
    while time.time() - start < max_wait:
        status_resp = client.get(f"/api/v1/jobs/{job_id}/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()

        if status_data["status"] == "DONE":
            done = True
            break
        elif status_data["status"] == "FAILED":
            pytest.fail(f"Job failed unexpectedly: {status_data.get('errorMessage')}")

        time.sleep(0.5)

    assert done, "Job did not finish within timeout"

    # 3. Download result
    res_resp = client.get(f"/api/v1/jobs/{job_id}/result")
    assert res_resp.status_code == 200
    assert len(res_resp.content) > 0

    # 4. Delete job
    del_resp = client.delete(f"/api/v1/jobs/{job_id}")
    assert del_resp.status_code == 204

    # 5. Status after delete should be 404
    after_del = client.get(f"/api/v1/jobs/{job_id}/status")
    assert after_del.status_code == 404
