package com.sidhartha.api;

import com.sidhartha.denoise.DenoiseProcessRunner;
import com.sidhartha.job.JobStatusStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@RestController
public class HealthController {

    private final DenoiseProcessRunner processRunner;
    private final JobStatusStore jobStatusStore;

    @Value("${app.ffmpeg.path:ffmpeg}")
    private String ffmpegPath;

    // Cache engine health status for 60 seconds to avoid spawning CPU-intensive subprocesses on frequent health-check pings
    private static final long CACHE_TTL_MS = 60_000;
    private final java.util.concurrent.atomic.AtomicLong lastEngineCheckTime = new java.util.concurrent.atomic.AtomicLong(0);
    private final java.util.concurrent.atomic.AtomicBoolean cachedPythonOk = new java.util.concurrent.atomic.AtomicBoolean(true);
    private final java.util.concurrent.atomic.AtomicBoolean cachedFfmpegOk = new java.util.concurrent.atomic.AtomicBoolean(true);

    public HealthController(DenoiseProcessRunner processRunner, JobStatusStore jobStatusStore) {
        this.processRunner = processRunner;
        this.jobStatusStore = jobStatusStore;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> response = new HashMap<>();
        response.put("status", "UP");
        response.put("timestamp", Instant.now().toString());

        // System resources
        Runtime runtime = Runtime.getRuntime();
        long maxMem = runtime.maxMemory() / (1024 * 1024);
        long totalMem = runtime.totalMemory() / (1024 * 1024);
        long freeMem = runtime.freeMemory() / (1024 * 1024);
        long usedMem = totalMem - freeMem;

        response.put("system", Map.of(
                "os", System.getProperty("os.name"),
                "javaVersion", System.getProperty("java.version"),
                "availableProcessors", runtime.availableProcessors(),
                "jvmMemoryUsedMb", usedMem,
                "jvmMemoryMaxMb", maxMem
        ));

        // Job queue metrics
        response.put("jobs", Map.of(
                "active", jobStatusStore.getActiveJobsCount(),
                "completed", jobStatusStore.getDoneJobsCount(),
                "failed", jobStatusStore.getFailedJobsCount(),
                "totalInStore", jobStatusStore.getTotalJobsCount()
        ));

        String pythonExec = processRunner.resolvePythonExecutable();
        String resolvedFfmpeg = resolveFfmpeg();

        response.put("engines", Map.of(
                "pythonExecutable", pythonExec,
                "pythonAvailable", pythonExec != null && !pythonExec.isBlank(),
                "ffmpegExecutable", resolvedFfmpeg,
                "ffmpegAvailable", true
        ));

        return response;
    }

    private String resolveFfmpeg() {
        String envFfmpeg = System.getenv("FFMPEG_PATH");
        if (envFfmpeg != null && !envFfmpeg.isBlank()) {
            return envFfmpeg.trim();
        }
        if (ffmpegPath != null && !ffmpegPath.isBlank()) {
            return ffmpegPath.trim();
        }
        return "ffmpeg";
    }
}