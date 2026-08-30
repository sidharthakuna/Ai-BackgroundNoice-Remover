package com.sidhartha.api;

import com.sidhartha.dto.JobAcceptedResponse;
import com.sidhartha.exception.AudioProcessingException;
import com.sidhartha.job.AudioJobService;
import com.sidhartha.job.JobRecord;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;

/**
 * Accepts an audio-enhancement upload and hands it off to AudioJobService
 * for async processing. This controller no longer runs ffmpeg, stages
 * Python modules, or invokes the denoise pipeline itself — see
 * AudioJobService (job package) and media/denoise packages for that.
 *
 * Response shape changed from the original synchronous version: this
 * returns 202 Accepted with a job ID immediately, rather than blocking
 * the request thread until processing finishes and returning the audio
 * bytes directly. Callers now poll JobController's status endpoint and
 * fetch the result once status is DONE. See job/AudioJobService's class
 * doc for why the file is read to bytes here, before the async handoff.
 */
@RestController
@RequestMapping("api/v1/audio")
public class AudioController {

    private final AudioJobService audioJobService;

    public AudioController(AudioJobService audioJobService) {
        this.audioJobService = audioJobService;
    }

    @PostMapping("/enhance")
    public ResponseEntity<JobAcceptedResponse> enhance(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "demucs", defaultValue = "false") boolean useDemucs,
            @RequestParam(value = "mode", defaultValue = "balanced") String mode,
            @RequestParam(value = "format", defaultValue = "wav") String format
    ) {
        JobRecord record = audioJobService.acceptAndStageJob(file, useDemucs, mode, format);

        audioJobService.runJob(record.getJobId(), file.getOriginalFilename(), useDemucs, mode, format);

        return ResponseEntity.accepted().body(JobAcceptedResponse.of(record.getJobId()));
    }
}