package com.sidhartha.job;

import com.sidhartha.denoise.DenoiseProcessRunner;
import com.sidhartha.denoise.DenoiseScriptStager;
import com.sidhartha.denoise.DenoiseServiceClient;
import com.sidhartha.exception.AudioProcessingException;
import com.sidhartha.media.FfmpegAudioExtractor;
import com.sidhartha.media.FfmpegFormatConverter;
import com.sidhartha.media.UploadValidator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.UUID;

/**
 * Orchestrates one audio-enhancement job end to end: validate the
 * upload, stage temp storage, extract audio from video if needed, run
 * the denoise pipeline (via persistent Python microservice or fallback),
 * convert to the requested output format, and clean up.
 */
@Service
public class AudioJobService {

    private static final Logger log = LoggerFactory.getLogger(AudioJobService.class);

    private static final Map<String, MediaType> CONTENT_TYPES = Map.of(
            "wav", MediaType.valueOf("audio/wav"),
            "mp3", MediaType.valueOf("audio/mpeg"),
            "flac", MediaType.valueOf("audio/flac"),
            "ogg", MediaType.valueOf("audio/ogg"),
            "m4a", MediaType.valueOf("audio/mp4"),
            "aac", MediaType.valueOf("audio/aac")
    );

    private final UploadValidator uploadValidator;
    private final FfmpegAudioExtractor audioExtractor;
    private final FfmpegFormatConverter formatConverter;
    private final DenoiseScriptStager scriptStager;
    private final DenoiseProcessRunner processRunner;
    private final DenoiseServiceClient serviceClient;
    private final JobStatusStore jobStatusStore;

    @org.springframework.beans.factory.annotation.Autowired
    public AudioJobService(UploadValidator uploadValidator,
                           FfmpegAudioExtractor audioExtractor,
                           FfmpegFormatConverter formatConverter,
                           DenoiseScriptStager scriptStager,
                           DenoiseProcessRunner processRunner,
                           DenoiseServiceClient serviceClient,
                           JobStatusStore jobStatusStore) {
        this.uploadValidator = uploadValidator;
        this.audioExtractor = audioExtractor;
        this.formatConverter = formatConverter;
        this.scriptStager = scriptStager;
        this.processRunner = processRunner;
        this.serviceClient = serviceClient;
        this.jobStatusStore = jobStatusStore;
    }

    public AudioJobService(UploadValidator uploadValidator,
                           FfmpegAudioExtractor audioExtractor,
                           FfmpegFormatConverter formatConverter,
                           DenoiseScriptStager scriptStager,
                           DenoiseProcessRunner processRunner,
                           JobStatusStore jobStatusStore) {
        this(uploadValidator, audioExtractor, formatConverter, scriptStager, processRunner,
                new DenoiseServiceClient(), jobStatusStore);
    }

    @jakarta.annotation.PostConstruct
    public void init() {
        jobStatusStore.setEvictionListener(this::cleanupJobRecordDir);
    }

    public JobRecord acceptAndStageJob(MultipartFile file, boolean useDemucs, String mode, String outputFormat) {
        if (file == null || file.isEmpty()) {
            throw new AudioProcessingException("No file was uploaded, or the file is empty.",
                    HttpStatus.BAD_REQUEST);
        }
        String cleanOriginalName = uploadValidator.sanitizeFilename(file.getOriginalFilename());
        String ext = uploadValidator.extractAndValidateExtension(cleanOriginalName);
        String format = uploadValidator.normalizeOutputFormat(outputFormat);
        String normMode = uploadValidator.normalizeMode(mode);

        String jobId = UUID.randomUUID().toString().substring(0, 8);
        Path jobDir;
        try {
            jobDir = Files.createTempDirectory("noise-job-" + jobId + "-");
        } catch (IOException e) {
            throw new AudioProcessingException("Could not allocate temporary storage for the job.",
                    HttpStatus.INTERNAL_SERVER_ERROR, e);
        }

        Path uploadedPath = jobDir.resolve("input." + ext);
        try (var in = file.getInputStream()) {
            Files.copy(in, uploadedPath, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            cleanupJobDir(jobDir, jobId);
            throw new AudioProcessingException("Could not stream the uploaded file to disk.",
                    HttpStatus.BAD_REQUEST, e);
        }

        JobRecord record = new JobRecord(jobId, cleanOriginalName);
        record.setJobDir(jobDir);
        record.setMode(normMode);
        record.setUseDemucs(useDemucs);
        record.setOutputFormat(format);
        record.setFileSizeBytes(file.getSize());
        jobStatusStore.put(record);
        return record;
    }

    public JobRecord acceptJob(MultipartFile file, boolean useDemucs, String outputFormat) {
        return acceptAndStageJob(file, useDemucs, "balanced", outputFormat);
    }

    @Async
    public void runJob(String jobId, String originalFilename, boolean useDemucs, String mode, String outputFormat) {
        JobRecord record = jobStatusStore.find(jobId)
                .orElseThrow(() -> new IllegalStateException(
                        "runJob called for unknown jobId " + jobId
                                + " — acceptAndStageJob() must run before runJob()"));

        String ext = uploadValidator.extractAndValidateExtension(originalFilename);
        String format = uploadValidator.normalizeOutputFormat(outputFormat);
        String normMode = uploadValidator.normalizeMode(mode);

        log.info("[job {}] starting: file='{}' demucs={} mode={} outputFormat={}",
                jobId, originalFilename, useDemucs, normMode, format);

        Path jobDir = record.getJobDir();
        if (jobDir == null || !Files.exists(jobDir)) {
            try (var stream = Files.newDirectoryStream(Path.of(System.getProperty("java.io.tmpdir")),
                    "noise-job-" + jobId + "-*")) {
                var iterator = stream.iterator();
                if (!iterator.hasNext()) {
                    record.markFailed("Could not locate temporary directory for the job.",
                            HttpStatus.INTERNAL_SERVER_ERROR);
                    return;
                }
                jobDir = iterator.next();
                record.setJobDir(jobDir);
            } catch (IOException e) {
                record.markFailed("Failed to access storage directory.", HttpStatus.INTERNAL_SERVER_ERROR);
                return;
            }
        }

        Path uploadedPath = jobDir.resolve("input." + ext);
        Path outputPath = jobDir.resolve("output.wav");

        try {
            Path denoiseInputPath = uploadedPath;
            try {
                record.markProgress(JobStatus.EXTRACTING,
                        uploadValidator.isVideoExtension(ext) ? "Extracting audio track from video" : "Preparing audio track", 15);
                denoiseInputPath = audioExtractor.extractAudioFromVideo(uploadedPath, jobDir, jobId);
            } catch (Exception e) {
                if (uploadValidator.isVideoExtension(ext)) {
                    throw e;
                }
                log.warn("[job {}] FFmpeg audio pre-conversion fallback to raw input: {}", jobId, e.getMessage());
                denoiseInputPath = uploadedPath;
            }

            // Primary: Use persistent Python microservice for instant inference and 0ms cold-start
            if (serviceClient != null && serviceClient.isAvailable()) {
                log.info("[job {}] Dispatching to persistent Python AI microservice", jobId);
                record.markProgress(JobStatus.DENOISING, "Processing with persistent AI engine", 30);
                serviceClient.process(denoiseInputPath, outputPath, normMode, useDemucs, jobId,
                        event -> record.markProgress(JobStatus.DENOISING, event.message(), event.progress()));
            } else {
                // Secondary Fallback: Subprocess runner
                log.info("[job {}] Python microservice unavailable, falling back to subprocess runner", jobId);
                Path scriptDir = scriptStager.stageInto(jobDir, jobId);
                record.markProgress(JobStatus.DENOISING, "Removing background noise", 30);
                processRunner.run(scriptDir, denoiseInputPath, outputPath, useDemucs, normMode, jobId,
                        line -> {
                            int pct = computeProgressPercentage(line);
                            record.markProgress(JobStatus.DENOISING, describeProgress(line), pct);
                        });
            }

            Path finalPath = outputPath;
            if (!format.equals("wav")) {
                record.markProgress(JobStatus.CONVERTING, "Converting to ." + format, 95);
                finalPath = formatConverter.convertOutputFormat(outputPath, jobDir, format, jobId);
            }

            record.markDone(finalPath, CONTENT_TYPES.getOrDefault(format, MediaType.valueOf("audio/wav")).toString());
            log.info("[job {}] complete: {}", jobId, finalPath);

        } catch (AudioProcessingException e) {
            record.markFailed(e.getMessage(), e.getStatus(), uploadedPath);
            cleanupJobDir(jobDir, jobId);
        } catch (Exception e) {
            log.error("[job " + jobId + "] unexpected failure", e);
            record.markFailed("Failed to process audio data for this job.",
                    HttpStatus.INTERNAL_SERVER_ERROR, uploadedPath);
            cleanupJobDir(jobDir, jobId);
        }
    }

    public void cancelJob(String jobId) {
        log.info("[job {}] Cancelling job and killing running tasks", jobId);
        if (serviceClient != null) {
            serviceClient.cancel(jobId);
        }
        processRunner.cancel(jobId);
        audioExtractor.cancel(jobId);
        formatConverter.cancel(jobId);

        jobStatusStore.find(jobId).ifPresent(this::cleanupJobRecordDir);
    }

    public void cleanupJobRecordDir(JobRecord record) {
        if (record == null) {
            return;
        }
        if (record.getJobDir() != null) {
            cleanupJobDir(record.getJobDir(), record.getJobId());
        } else if (record.getOutputPath() != null) {
            cleanupJobDir(record.getOutputPath(), record.getJobId());
        }
    }

    public void cleanupJobDir(Path pathOrDir, String jobId) {
        if (pathOrDir == null) {
            return;
        }
        Path jobDir;
        if (Files.isDirectory(pathOrDir) && pathOrDir.getFileName().toString().contains("noise-job-")) {
            jobDir = pathOrDir;
        } else if (pathOrDir.getParent() != null && pathOrDir.getParent().getFileName().toString().contains("noise-job-")) {
            jobDir = pathOrDir.getParent();
        } else {
            log.warn("[job {}] Refusing to delete non-job directory: {}", jobId, pathOrDir);
            return;
        }

        try (var files = Files.walk(jobDir)) {
            files.sorted((a, b) -> b.getNameCount() - a.getNameCount())
                    .forEach(p -> {
                        try {
                            Files.deleteIfExists(p);
                        } catch (IOException ignored) {
                        }
                    });
        } catch (IOException e) {
            log.warn("[job {}] cleanup of {} failed: {}", jobId, jobDir, e.getMessage());
        }
    }

    private int computeProgressPercentage(String rawLine) {
        if (rawLine == null) return 30;
        String line = rawLine.toLowerCase();
        if (line.contains("analyzing input")) return 35;
        if (line.contains("pre-filtering")) return 45;
        if (line.contains("voice activity")) return 55;
        if (line.contains("deepfilternet")) return 70;
        if (line.contains("dynamic range") || line.contains("dynamics")) return 85;
        if (line.contains("loudness") || line.contains("mastering")) return 92;
        if (line.contains("reconstructing")) return 97;
        if (line.contains("done")) return 99;
        return 60;
    }

    private String describeProgress(String rawLine) {
        if (rawLine == null || !rawLine.startsWith("PROGRESS:")) {
            return "Removing background noise";
        }
        String body = rawLine.substring("PROGRESS:".length()).trim();
        if (body.startsWith("spectral_subtract skipped") || body.startsWith("near-zero noise floor")) {
            return "Removing background noise";
        }
        if (body.startsWith("stereo length mismatch")) {
            return "Finalizing stereo output";
        }
        if (body.startsWith("done")) {
            return "Finishing up";
        }
        return body;
    }
}