package com.sidhartha.job;

import org.springframework.http.HttpStatus;

import java.nio.file.Path;
import java.time.Instant;

/**
 * Mutable state for a single audio processing job.
 * Stores lifecycle progress, metadata, error state, and output file locations.
 */
public class JobRecord {

    private final String jobId;
    private final Instant createdAt;
    private final String originalFilename;

    private volatile Path jobDir;
    private volatile JobStatus status;
    private volatile String progressMessage;
    private volatile int progressPercentage;
    private volatile Path outputPath;
    private volatile String outputContentType;
    private volatile String errorMessage;
    private volatile HttpStatus errorStatus;

    private volatile String mode = "balanced";
    private volatile boolean useDemucs = false;
    private volatile String outputFormat = "wav";
    private volatile long fileSizeBytes = 0;
    private volatile long processingTimeMs = 0;
    private volatile Instant finishedAt;

    public JobRecord(String jobId, String originalFilename) {
        this.jobId = jobId;
        this.originalFilename = originalFilename;
        this.createdAt = Instant.now();
        this.status = JobStatus.QUEUED;
        this.progressMessage = "Queued";
        this.progressPercentage = 5;
    }

    public Path getJobDir() {
        return jobDir;
    }

    public void setJobDir(Path jobDir) {
        this.jobDir = jobDir;
    }

    // ── Reads ───────────────────────────────────────────────────────────

    public String getJobId() {
        return jobId;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public String getOriginalFilename() {
        return originalFilename;
    }

    public JobStatus getStatus() {
        return status;
    }

    public String getProgressMessage() {
        return progressMessage;
    }

    public int getProgressPercentage() {
        return progressPercentage;
    }

    public Path getOutputPath() {
        return outputPath;
    }

    public String getOutputContentType() {
        return outputContentType;
    }

    public String getErrorMessage() {
        return errorMessage;
    }

    public HttpStatus getErrorStatus() {
        return errorStatus;
    }

    public String getMode() {
        return mode;
    }

    public void setMode(String mode) {
        this.mode = mode;
    }

    public boolean isUseDemucs() {
        return useDemucs;
    }

    public void setUseDemucs(boolean useDemucs) {
        this.useDemucs = useDemucs;
    }

    public String getOutputFormat() {
        return outputFormat;
    }

    public void setOutputFormat(String outputFormat) {
        this.outputFormat = outputFormat;
    }

    public long getFileSizeBytes() {
        return fileSizeBytes;
    }

    public void setFileSizeBytes(long fileSizeBytes) {
        this.fileSizeBytes = fileSizeBytes;
    }

    public long getProcessingTimeMs() {
        return processingTimeMs;
    }

    public Instant getFinishedAt() {
        return finishedAt;
    }

    // ── Transitions (called only by AudioJobService, from the async worker) ──

    public synchronized void markProgress(JobStatus status, String message) {
        this.status = status;
        this.progressMessage = message;
    }

    public synchronized void markProgress(JobStatus status, String message, int progressPercentage) {
        this.status = status;
        this.progressMessage = message;
        this.progressPercentage = Math.max(0, Math.min(100, progressPercentage));
    }

    public synchronized void markDone(Path outputPath, String outputContentType) {
        markDone(outputPath, outputContentType, Instant.now().toEpochMilli() - createdAt.toEpochMilli());
    }

    public synchronized void markDone(Path outputPath, String outputContentType, long processingTimeMs) {
        this.outputPath = outputPath;
        this.outputContentType = outputContentType;
        this.status = JobStatus.DONE;
        this.progressMessage = "Complete";
        this.progressPercentage = 100;
        this.processingTimeMs = processingTimeMs;
        this.finishedAt = Instant.now();
    }

    public synchronized void markFailed(String errorMessage, HttpStatus errorStatus) {
        this.errorMessage = errorMessage;
        this.errorStatus = errorStatus;
        this.status = JobStatus.FAILED;
        this.progressMessage = "Failed";
        this.finishedAt = Instant.now();
    }

    public synchronized void markFailed(String errorMessage, HttpStatus errorStatus, Path jobFileHint) {
        this.errorMessage = errorMessage;
        this.errorStatus = errorStatus;
        this.status = JobStatus.FAILED;
        this.progressMessage = "Failed";
        this.outputPath = jobFileHint;
        this.finishedAt = Instant.now();
    }
}