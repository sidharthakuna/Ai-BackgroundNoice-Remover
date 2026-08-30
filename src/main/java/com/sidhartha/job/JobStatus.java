package com.sidhartha.job;

/**
 * Lifecycle states for an audio processing job. Ordered roughly as a job
 * progresses, though EXTRACTING is skipped for non-video uploads and
 * CONVERTING is skipped when the requested output format is wav.
 *
 * QUEUED      — job accepted, not yet picked up by the async executor
 * EXTRACTING  — pulling the audio track out of a video container (ffmpeg)
 * DENOISING   — running the Python DSP pipeline (the long step)
 * CONVERTING  — re-encoding the wav result into the requested output format
 * DONE        — result bytes are available at JobRecord#outputPath
 * FAILED      — see JobRecord#errorMessage / #httpStatus
 */
public enum JobStatus {
    QUEUED,
    EXTRACTING,
    DENOISING,
    CONVERTING,
    DONE,
    FAILED
}