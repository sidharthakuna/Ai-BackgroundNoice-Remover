package com.sidhartha.dto;

/**
 * JSON body returned from POST /api/v1/audio/enhance once the job is
 * accepted and queued. The caller polls
 * GET /api/v1/jobs/{jobId}/status with this jobId, then downloads from
 * GET /api/v1/jobs/{jobId}/result once status is DONE.
 */
public record JobAcceptedResponse(
        String jobId,
        String statusUrl
) {
    public static JobAcceptedResponse of(String jobId) {
        return new JobAcceptedResponse(jobId, "/api/v1/jobs/" + jobId + "/status");
    }
}