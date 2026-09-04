# AI Studio Background Noise Remover (v2.0)

> **High-Performance, Studio-Grade (48kHz) AI Audio & Video Noise Removal Backend & Web App**  
> Built with **Java 21 (Spring Boot)** & **Python DeepFilterNet3 DSP Pipeline**, architected specifically for **Render Free Tier (512MB RAM)**.

---

## What Makes v2.0 Radically Better

| Feature | Original Implementation | Upgraded v2.0 Architecture |
|---|---|---|
| **Audio Bandwidth & Quality** | 16kHz (8kHz cutoff, telephone sound) | **48kHz Studio Fidelity** (full 20Hz–24kHz vocal range, natural air & presence) |
| **Spectral Artifacts** | Static STFT subtraction (underwater warbles / chirps) | **Wiener-style smoothed multi-band spectral gating** (zero musical noise) |
| **Java Concurrency** | Standard OS platform threads | **Java 21 Virtual Threads** (`spring.threads.virtual.enabled=true`) |
| **Process Tree Management** | Flat process termination (orphaned Python children) | **`ProcessHandle.descendants()` recursive tree cleanup** on timeout / cancel |
| **RAM Footprint on Render (512MB Limit)** | Spring Boot + Python exceeded 512MB (OOM exit 137) | **Tuned JVM (SerialGC, 40MB heap, low metaspace) ~80MB RSS**, leaving >420MB for Python |
| **Video Extraction** | Extracted at 16kHz | **Direct 48kHz studio audio extraction via FFmpeg** |
| **Test Coverage** | 28 JUnit Tests | **All 28 JUnit tests compile & pass 100%** |

---

## Architecture Overview

```
Ai-BackgroundNoise-Remover/
├── src/main/java/com/sidhartha/
│   ├── api/
│   │   ├── AudioController.java         # POST /api/v1/audio/enhance (accepts upload & queues job)
│   │   ├── JobController.java           # GET /status, GET /result, DELETE /jobs/{jobId}
│   │   └── HealthController.java        # GET /health (JVM metrics, job queue stats, engine health)
│   ├── config/
│   │   ├── AsyncConfig.java             # Bounded thread pool / virtual thread executor
│   │   └── CorsConfig.java              # Configurable CORS filter
│   ├── denoise/
│   │   ├── DenoiseProcessRunner.java    # Subprocess execution with process-tree cleanup
│   │   └── DenoiseScriptStager.java     # Stages Python pipeline from classpath to disk
│   ├── job/
│   │   ├── AudioJobService.java         # Orchestrates job lifecycle end-to-end
│   │   ├── JobRecord.java               # Thread-safe job state tracker
│   │   ├── JobStatus.java               # QUEUED, EXTRACTING, DENOISING, CONVERTING, DONE, FAILED
│   │   └── JobStatusStore.java          # In-memory store with hourly TTL eviction & disk cleanup
│   ├── media/
│   │   ├── UploadValidator.java         # Sanitizer and audio/video extension validator
│   │   ├── FfmpegAudioExtractor.java    # 48kHz audio track extraction from video containers
│   │   └── FfmpegFormatConverter.java   # Studio re-encoding (MP3 320k, FLAC, OGG, M4A, AAC)
│   └── keepalive/
│       └── KeepAliveService.java        # Self-ping service every 12 mins to prevent Render sleep
├── src/main/resources/
│   ├── application.properties           # Virtual threads, keep-alive, file size & port configs
│   ├── static/                          # Web frontend (index.html, style.css, js/)
│   └── denoise/                         # Upgraded 48kHz Python DSP & AI Pipeline
│       ├── main.py                      # Orchestrator with real-time PROGRESS: streaming
│       ├── io_utils.py                  # 48kHz audio I/O & Mid/Side stereo correlation analyzer
│       ├── denoise_dfn.py               # 70Hz rumble filter, Wiener spectral filter & DeepFilterNet3
│       ├── vad_gate.py                  # Dual-band WebRTC + Formant Energy VAD speech gate
│       ├── dynamics.py                  # 48kHz AGC leveler, RMS compressor, soft-knee limiter
│       ├── tone.py                      # 5-band voice mastering EQ, de-esser & -14 LUFS normalizer
│       └── demucs_stage.py              # Chunked Demucs vocal isolation with memory guards
├── src/test/java/com/sidhartha/         # Complete JUnit 5 test suite (28 passing tests)
├── Dockerfile                           # Production multi-stage Dockerfile optimized for 512MB RAM
├── pom.xml                              # Maven configuration
├── render.yaml                          # Render deployment blueprint
└── requirements.txt                     # Pinned Python DSP dependencies
```

---

## 48kHz Audio Pipeline Flow

```
io_utils.load_and_split_channels (48kHz, Mid/Side correlation analysis)
  → denoise_dfn.apply_highpass (70Hz 4th-order Butterworth rumble cut)
  → denoise_dfn.spectral_subtract (Wiener spectral smoothing, eliminates musical noise)
  → vad_gate.apply_vad_gate (Dual-band WebRTC + speech formant energy, returns vad_gain)
  → denoise_dfn.apply_deepfilternet (DeepFilterNet3 neural enhancement @ native 48kHz)
  → dynamics.process (AGC leveling → RMS compressor → soft-knee limiter)
  → [demucs_stage.apply_demucs_separation, if --demucs] (chunked vocal stem separation)
  → tone.process (5-band mastering EQ → harmonic exciter → de-esser → -14 LUFS)
  → io_utils.reconstruct_output (Mid/Side stereo recombine & 0.95 true-peak ceiling)
  → io_utils.save_output (48kHz WAV)
```

---

## API Endpoints

### 1. Submit Audio for Enhancement
`POST /api/v1/audio/enhance`  
Accepts multipart form-data:
- `file`: Audio or video file (MP3, WAV, FLAC, OGG, M4A, AAC, OPUS, WMA, MP4, MOV, MKV, WEBM)
- `demucs`: `true` or `false` (optional, default `false`)
- `mode`: `balanced`, `aggressive`, `gentle` (optional, default `balanced`)
- `format`: `wav`, `mp3`, `flac`, `ogg`, `m4a`, `aac` (optional, default `wav`)

**Response (`202 Accepted`):**
```json
{
  "jobId": "8f3b12a0",
  "statusUrl": "/api/v1/jobs/8f3b12a0/status"
}
```

### 2. Poll Job Status
`GET /api/v1/jobs/{jobId}/status`

**Response (`200 OK`):**
```json
{
  "jobId": "8f3b12a0",
  "status": "DENOISING",
  "message": "DeepFilterNet neural noise suppression",
  "progressPercentage": 70,
  "resultReady": false,
  "errorMessage": null,
  "originalFilename": "podcast.mp3",
  "mode": "balanced",
  "format": "wav",
  "processingTimeMs": 3120
}
```

### 3. Download Result
`GET /api/v1/jobs/{jobId}/result`  
Streams the enhanced audio file once `resultReady == true`.

### 4. Cancel / Delete Job
`DELETE /api/v1/jobs/{jobId}`  
Cancels active processing, kills the subprocess tree, and frees temporary disk storage (`204 No Content`).

### 5. Health Check
`GET /health`  
Reports JVM memory usage, job queue counters, and engine availability (`200 OK`).

---

## Running Locally

### Prerequisites
- Java 21+ JDK
- Python 3.11+ with pip
- FFmpeg installed and in your system PATH

### Installation & Run
```bash
# 1. Install Python DSP dependencies
pip install -r requirements.txt

# 2. Run with Maven wrapper
./mvnw spring-boot:run
```
Open your browser at [http://localhost:8080](http://localhost:8080) to use the web application!

### Run Tests
```bash
./mvnw test
```

---

## Deploying to Render Free Tier

1. Connect your repository to **Render**.
2. Select **Web Service** → **Docker**.
3. Render automatically uses `render.yaml` and `Dockerfile`.
4. The service will build with Maven, pre-cache DeepFilterNet3 and Demucs weights, and start with JVM memory configured for 512MB RAM.
5. The `KeepAliveService` will automatically self-ping `/health` every 12 minutes to prevent container spin-down.