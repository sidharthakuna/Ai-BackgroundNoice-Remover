package com.sidhartha.denoise;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sidhartha.exception.AudioProcessingException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Consumer;

/**
 * High-performance HTTP client for communicating with the internal Python AI microservice (127.0.0.1:5000).
 * Pre-warmed neural models in the Python service eliminate cold-start subprocess latency.
 * Streams real-time NDJSON progress events directly into JobRecord.
 */
@Component
public class DenoiseServiceClient {

    private static final Logger log = LoggerFactory.getLogger(DenoiseServiceClient.class);

    @Value("${app.denoise.service.url:http://127.0.0.1:5000}")
    private String serviceUrl = "http://127.0.0.1:5000";

    @Value("${app.denoise.service.enabled:true}")
    private boolean serviceEnabled = true;

    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;

    public DenoiseServiceClient() {
        this(HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(3))
                .build(), new ObjectMapper());
    }

    public DenoiseServiceClient(HttpClient httpClient, ObjectMapper objectMapper) {
        this.httpClient = httpClient;
        this.objectMapper = objectMapper;
    }

    /**
     * Checks if the persistent Python microservice is active and healthy.
     */
    public boolean isAvailable() {
        if (!serviceEnabled || serviceUrl == null || serviceUrl.isBlank()) {
            return false;
        }
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(serviceUrl + "/health"))
                    .timeout(Duration.ofSeconds(2))
                    .GET()
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            return response.statusCode() == 200;
        } catch (Exception e) {
            log.debug("Python microservice at {} not reachable: {}", serviceUrl, e.getMessage());
            return false;
        }
    }

    /**
     * Queries detailed health metrics from the Python microservice.
     */
    public Map<String, Object> checkHealth() {
        if (serviceUrl != null && !serviceUrl.isBlank()) {
            try {
                HttpRequest request = HttpRequest.newBuilder()
                        .uri(URI.create(serviceUrl + "/health"))
                        .timeout(Duration.ofSeconds(2))
                        .GET()
                        .build();
                HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() == 200) {
                    return objectMapper.readValue(response.body(), Map.class);
                }
            } catch (Exception e) {
                log.debug("Python microservice health check failed: {}", e.getMessage());
            }
        }
        Map<String, Object> fallback = new HashMap<>();
        fallback.put("status", "UNAVAILABLE");
        fallback.put("serviceUrl", serviceUrl);
        return fallback;
    }

    /**
     * Invokes the microservice to process an audio job and streams NDJSON progress updates.
     */
    public void process(Path inputPath, Path outputPath, String mode, boolean useDemucs,
                        String jobId, Consumer<ProgressEvent> progressListener) {
        String url = serviceUrl + "/process";
        Map<String, Object> payload = new HashMap<>();
        payload.put("job_id", jobId);
        payload.put("input_path", inputPath.toAbsolutePath().toString());
        payload.put("output_path", outputPath.toAbsolutePath().toString());
        payload.put("mode", mode != null ? mode : "balanced");
        payload.put("use_demucs", useDemucs);

        try {
            String jsonBody = objectMapper.writeValueAsString(payload);
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(Duration.ofMinutes(15))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/x-ndjson")
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody, StandardCharsets.UTF_8))
                    .build();

            HttpResponse<InputStream> response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());

            if (response.statusCode() != 200) {
                throw new AudioProcessingException("Python microservice returned HTTP " + response.statusCode(),
                        HttpStatus.UNPROCESSABLE_ENTITY);
            }

            try (BufferedReader reader = new BufferedReader(new InputStreamReader(response.body(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    line = line.trim();
                    if (line.isEmpty()) {
                        continue;
                    }
                    try {
                        JsonNode node = objectMapper.readTree(line);
                        int progress = node.path("progress").asInt(50);
                        String stage = node.path("stage").asText("DENOISING");
                        String message = node.path("message").asText("Processing audio");
                        String status = node.path("status").asText("RUNNING");

                        if ("FAILED".equalsIgnoreCase(status)) {
                            throw new AudioProcessingException("Audio processing failed: " + message,
                                    HttpStatus.UNPROCESSABLE_ENTITY);
                        }
                        if ("CANCELLED".equalsIgnoreCase(status)) {
                            throw new AudioProcessingException("Job was cancelled.", HttpStatus.REQUEST_TIMEOUT);
                        }

                        progressListener.accept(new ProgressEvent(progress, stage, message));
                    } catch (AudioProcessingException ape) {
                        throw ape;
                    } catch (Exception parseEx) {
                        log.warn("[job {}] Failed to parse progress line: {}", jobId, line);
                    }
                }
            }

            if (!Files.exists(outputPath)) {
                throw new AudioProcessingException("Processing finished but produced no output file.",
                        HttpStatus.UNPROCESSABLE_ENTITY);
            }

        } catch (AudioProcessingException ape) {
            throw ape;
        } catch (Exception e) {
            log.error("[job {}] Error communicating with Python microservice: {}", jobId, e.getMessage());
            throw new AudioProcessingException("Audio processing microservice error: " + e.getMessage(),
                    HttpStatus.INTERNAL_SERVER_ERROR, e);
        }
    }

    /**
     * Sends cooperative cancellation signal to the Python microservice.
     */
    public boolean cancel(String jobId) {
        if (serviceUrl == null || serviceUrl.isBlank()) {
            return false;
        }
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(serviceUrl + "/jobs/" + jobId + "/cancel"))
                    .timeout(Duration.ofSeconds(3))
                    .POST(HttpRequest.BodyPublishers.noBody())
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            return response.statusCode() == 200;
        } catch (Exception e) {
            log.warn("[job {}] Failed to send cancel request to Python microservice: {}", jobId, e.getMessage());
            return false;
        }
    }

    public record ProgressEvent(int progress, String stage, String message) {}

    public void setServiceUrl(String serviceUrl) {
        this.serviceUrl = serviceUrl;
    }

    public void setServiceEnabled(boolean serviceEnabled) {
        this.serviceEnabled = serviceEnabled;
    }

    public String getServiceUrl() {
        return serviceUrl;
    }
}
