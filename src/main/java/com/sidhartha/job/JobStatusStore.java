package com.sidhartha.job;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * In-memory registry of JobRecords, keyed by jobId.
 * Tracks active and completed jobs and handles scheduled expiry.
 */
@Component
public class JobStatusStore {

    @Value("${app.jobs.retention-hours:2}")
    private long retentionHours = 2;

    private final Map<String, JobRecord> jobs = new ConcurrentHashMap<>();

    private java.util.function.Consumer<JobRecord> evictionListener;

    public void setEvictionListener(java.util.function.Consumer<JobRecord> evictionListener) {
        this.evictionListener = evictionListener;
    }

    public void put(JobRecord record) {
        jobs.put(record.getJobId(), record);
    }

    public Optional<JobRecord> find(String jobId) {
        return Optional.ofNullable(jobs.get(jobId));
    }

    public void remove(String jobId) {
        jobs.remove(jobId);
    }

    public int getTotalJobsCount() {
        return jobs.size();
    }

    public long getActiveJobsCount() {
        return jobs.values().stream()
                .filter(r -> r.getStatus() != JobStatus.DONE && r.getStatus() != JobStatus.FAILED)
                .count();
    }

    public long getDoneJobsCount() {
        return jobs.values().stream()
                .filter(r -> r.getStatus() == JobStatus.DONE)
                .count();
    }

    public long getFailedJobsCount() {
        return jobs.values().stream()
                .filter(r -> r.getStatus() == JobStatus.FAILED)
                .count();
    }

    /**
     * Evicts jobs older than retention window. Runs hourly.
     */
    @Scheduled(fixedRate = 60 * 60 * 1000)
    public void evictExpired() {
        Duration retention = Duration.ofHours(Math.max(1, retentionHours));
        Instant cutoff = Instant.now().minus(retention);
        jobs.values().removeIf(record -> {
            if (record.getCreatedAt().isBefore(cutoff)) {
                if (evictionListener != null) {
                    try {
                        evictionListener.accept(record);
                    } catch (Exception ignored) {
                    }
                }
                return true;
            }
            return false;
        });
    }
}