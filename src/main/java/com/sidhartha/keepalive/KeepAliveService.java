package com.sidhartha.keepalive;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * Periodically sends a lightweight HTTP ping to the application's public URL
 * (e.g., Render's RENDER_EXTERNAL_URL) every 12 minutes to prevent the free tier
 * container from spinning down due to inbound inactivity.
 */
@Service
public class KeepAliveService {

    private static final Logger log = LoggerFactory.getLogger(KeepAliveService.class);

    @Value("${app.keepalive.enabled:true}")
    private boolean enabled;

    @Value("${app.keepalive.url:${RENDER_EXTERNAL_URL:}}")
    private String targetUrl;

    private final HttpClient httpClient;

    public KeepAliveService() {
        this(HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build());
    }

    public KeepAliveService(HttpClient httpClient) {
        this.httpClient = httpClient;
    }

    @Scheduled(
            initialDelayString = "${app.keepalive.initial-delay-ms:60000}",
            fixedRateString = "${app.keepalive.fixed-rate-ms:720000}"
    )
    public void ping() {
        if (!enabled) {
            return;
        }

        String rawUrl = targetUrl != null ? targetUrl.trim() : "";
        if (rawUrl.isEmpty()) {
            log.debug("[keep-alive] No external URL configured (RENDER_EXTERNAL_URL / app.keepalive.url is empty). Ping skipped.");
            return;
        }

        String pingUrl = formatPingUrl(rawUrl);

        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(pingUrl))
                    .timeout(Duration.ofSeconds(15))
                    .header("User-Agent", "AI-Noise-Remover-KeepAlive/1.0")
                    .GET()
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            log.info("[keep-alive] Self-ping to {} -> Status {}", pingUrl, response.statusCode());
        } catch (Exception e) {
            log.warn("[keep-alive] Self-ping to {} failed: {}", pingUrl, e.getMessage());
        }
    }

    public String formatPingUrl(String rawUrl) {
        String url = rawUrl.trim();
        if (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        if (!url.endsWith("/health")) {
            url = url + "/health";
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "https://" + url;
        }
        return url;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public void setTargetUrl(String targetUrl) {
        this.targetUrl = targetUrl;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public String getTargetUrl() {
        return targetUrl;
    }
}
