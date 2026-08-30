package com.sidhartha.dto;

import com.sidhartha.job.JobRecord;
import com.sidhartha.job.JobStatus;

/**
 * JSON body returned from GET /api/v1/jobs/{jobId}/status.
 */
public record JobStatusResponse(
        String jobId,
        JobStatus status,
        String message,
        int progressPercentage,
        boolean resultReady,
        String errorMessage,
        String originalFilename,
        String mode,
        String format,
        long processingTimeMs
) {
    public static JobStatusResponse from(JobRecord record) {
        return new JobStatusResponse(
                record.getJobId(),
                record.getStatus(),
                record.getProgressMessage(),
                record.getProgressPercentage(),
                record.getStatus() == JobStatus.DONE,
                record.getStatus() == JobStatus.FAILED ? record.getErrorMessage() : null,
                record.getOriginalFilename(),
                record.getMode(),
                record.getOutputFormat(),
                record.getProcessingTimeMs()
        );
    }
}