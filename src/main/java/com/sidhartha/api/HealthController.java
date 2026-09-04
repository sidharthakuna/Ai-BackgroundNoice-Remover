package com.sidhartha.api;

import com.sidhartha.denoise.DenoiseProcessRunner;
import com.sidhartha.denoise.DenoiseServiceClient;
import com.sidhartha.job.JobStatusStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

@RestController
public class HealthController {

    private final DenoiseProcessRunner processRunner;
    private final DenoiseServiceClient serviceClient;
    private final JobStatusStore jobStatusStore;

    @Value("${app.ffmpeg.path:ffmpeg}")
    private String ffmpegPath;

    @org.springframework.beans.factory.annotation.Autowired
    public HealthController(DenoiseProcessRunner processRunner,
                            DenoiseServiceClient serviceClient,
                            JobStatusStore jobStatusStore) {
        this.processRunner = processRunner;
        this.serviceClient = serviceClient;
        this.jobStatusStore = jobStatusStore;
    }

    public HealthController(DenoiseProcessRunner processRunner, JobStatusStore jobStatusStore) {
        this(processRunner, new DenoiseServiceClient(), jobStatusStore);
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> response = new HashMap<>();
        response.put("status", "UP");
        response.put("timestamp", Instant.now().toString());

        // System JVM resources
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

        Map<String, Object> engines = new HashMap<>();
        engines.put("pythonExecutable", pythonExec);
        engines.put("pythonAvailable", pythonExec != null && !pythonExec.isBlank());
        engines.put("ffmpegExecutable", resolvedFfmpeg);
        engines.put("ffmpegAvailable", true);

        if (serviceClient != null) {
            boolean microserviceUp = serviceClient.isAvailable();
            engines.put("pythonMicroserviceUp", microserviceUp);
            if (microserviceUp) {
                engines.put("pythonMicroserviceMetrics", serviceClient.checkHealth());
            }
        }

        response.put("engines", engines);

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