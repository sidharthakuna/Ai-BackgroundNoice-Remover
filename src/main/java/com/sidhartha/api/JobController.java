package com.sidhartha.api;

import com.sidhartha.dto.JobStatusResponse;
import com.sidhartha.exception.AudioProcessingException;
import com.sidhartha.job.AudioJobService;
import com.sidhartha.job.JobRecord;
import com.sidhartha.job.JobStatus;
import com.sidhartha.job.JobStatusStore;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.function.Consumer;

/**
 * Status polling, real-time SSE streaming, and result retrieval for jobs.
 * Supports both:
 * 1. Traditional polling via GET /api/v1/jobs/{jobId}/status
 * 2. Real-time Server-Sent Events (SSE) via GET /api/v1/jobs/{jobId}/events
 */
@RestController
@RequestMapping("api/v1/jobs")
public class JobController {

    private final JobStatusStore jobStatusStore;
    private final AudioJobService audioJobService;

    public JobController(JobStatusStore jobStatusStore, AudioJobService audioJobService) {
        this.jobStatusStore = jobStatusStore;
        this.audioJobService = audioJobService;
    }

    @GetMapping("/{jobId}/status")
    public ResponseEntity<JobStatusResponse> status(@PathVariable String jobId) {
        JobRecord record = findOrThrow(jobId);
        return ResponseEntity.ok(JobStatusResponse.from(record));
    }

    /**
     * Real-time Server-Sent Events (SSE) stream.
     * Pushes progress updates immediately to the client as DSP stages complete.
     */
    @GetMapping(value = "/{jobId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamEvents(@PathVariable String jobId) {
        JobRecord record = findOrThrow(jobId);
        SseEmitter emitter = new SseEmitter(15 * 60 * 1000L); // 15 minute timeout

        Consumer<JobRecord> listener = rec -> {
            try {
                emitter.send(SseEmitter.event()
                        .name("progress")
                        .data(JobStatusResponse.from(rec)));
                if (rec.getStatus() == JobStatus.DONE || rec.getStatus() == JobStatus.FAILED) {
                    emitter.complete();
                }
            } catch (Exception e) {
                emitter.completeWithError(e);
            }
        };

        record.addListener(listener);
        emitter.onCompletion(() -> record.removeListener(listener));
        emitter.onTimeout(() -> {
            record.removeListener(listener);
            emitter.complete();
        });
        emitter.onError(e -> record.removeListener(listener));

        return emitter;
    }

    @GetMapping("/{jobId}/result")
    public ResponseEntity<Resource> result(@PathVariable String jobId) {
        JobRecord record = findOrThrow(jobId);

        if (record.getStatus() == JobStatus.FAILED) {
            throw new AudioProcessingException(record.getErrorMessage(), record.getErrorStatus());
        }
        if (record.getStatus() != JobStatus.DONE) {
            throw new AudioProcessingException(
                    "Job is not finished yet (status: " + record.getStatus() + "). Poll /status first.",
                    HttpStatus.CONFLICT);
        }

        Path outputPath = record.getOutputPath();
        if (outputPath == null || !Files.exists(outputPath)) {
            throw new AudioProcessingException(
                    "The result file is no longer available. It may have expired.",
                    HttpStatus.GONE);
        }

        long fileSize;
        try {
            fileSize = Files.size(outputPath);
        } catch (IOException e) {
            throw new AudioProcessingException(
                    "Could not determine output file size.",
                    HttpStatus.INTERNAL_SERVER_ERROR, e);
        }

        String extension = outputPath.getFileName().toString();
        extension = extension.contains(".")
                ? extension.substring(extension.lastIndexOf('.') + 1)
                : "wav";

        MediaType contentType = record.getOutputContentType() != null
                ? MediaType.valueOf(record.getOutputContentType())
                : MediaType.valueOf("audio/wav");

        String baseName = "enhanced_audio";
        if (record.getOriginalFilename() != null && !record.getOriginalFilename().isBlank()) {
            String orig = record.getOriginalFilename();
            int dot = orig.lastIndexOf('.');
            baseName = (dot > 0 ? orig.substring(0, dot) : orig) + "_enhanced";
        }

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(contentType);
        headers.setContentLength(fileSize);
        headers.setContentDisposition(
                ContentDisposition.attachment()
                        .filename(baseName + "." + extension, StandardCharsets.UTF_8)
                        .build());

        Resource resource = new FileSystemResource(outputPath);
        return ResponseEntity.ok()
                .headers(headers)
                .body(resource);
    }

    /**
     * Cancels the job if currently running (kills active processes),
     * deletes the temp directory, and removes the job from the store.
     */
    @DeleteMapping("/{jobId}")
    public ResponseEntity<Void> delete(@PathVariable String jobId) {
        audioJobService.cancelJob(jobId);
        jobStatusStore.remove(jobId);
        return ResponseEntity.noContent().build();
    }

    private JobRecord findOrThrow(String jobId) {
        return jobStatusStore.find(jobId)
                .orElseThrow(() -> new AudioProcessingException(
                        "No job found with id '" + jobId + "'. It may have expired.",
                        HttpStatus.NOT_FOUND));
    }
}