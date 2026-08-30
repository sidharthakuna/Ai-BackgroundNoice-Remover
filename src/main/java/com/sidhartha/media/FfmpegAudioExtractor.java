package com.sidhartha.media;

import com.sidhartha.exception.AudioProcessingException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * Extracts the audio track from a video file (mp4/mov/mkv/webm) into a
 * plain WAV that the denoise pipeline can read.
 */
@Component
public class FfmpegAudioExtractor {

    private static final Logger log = LoggerFactory.getLogger(FfmpegAudioExtractor.class);

    @Value("${app.ffmpeg.path:ffmpeg}")
    private String ffmpegExecutable;

    private final Map<String, Process> activeProcesses = new ConcurrentHashMap<>();

    public Path extractAudioFromVideo(Path videoPath, Path jobDir, String jobId) {
        Path extractedPath = jobDir.resolve("extracted-audio.wav");
        String exec = resolveFfmpeg();

        ProcessBuilder pb = new ProcessBuilder(
                exec, "-nostdin", "-y", "-i", videoPath.toString(),
                "-vn",                  // drop video stream entirely
                "-ar", "16000",          // extract directly at DSP native 16kHz
                "-acodec", "pcm_s16le",  // plain PCM WAV
                "-loglevel", "error",
                extractedPath.toString());
        pb.redirectErrorStream(true);

        Process process = null;
        try {
            process = pb.start();
            activeProcesses.put(jobId, process);

            final Process procRef = process;
            CompletableFuture<String> outputReader = CompletableFuture.supplyAsync(() -> {
                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(procRef.getInputStream(), StandardCharsets.UTF_8))) {
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) {
                        sb.append(line).append('\n');
                    }
                    return sb.toString();
                } catch (IOException e) {
                    return "";
                }
            });

            boolean finished = process.waitFor(5, TimeUnit.MINUTES);
            if (!finished) {
                process.destroyForcibly();
                throw new AudioProcessingException(
                        "Extracting audio from the video timed out.", HttpStatus.REQUEST_TIMEOUT);
            }
            int exitCode = process.exitValue();
            String out = outputReader.getNow("");
            log.info("[job {}] ffmpeg audio extraction exit={}", jobId, exitCode);

            if (exitCode != 0 || !Files.exists(extractedPath)) {
                log.warn("[job {}] ffmpeg audio extraction failed, output:\n{}", jobId, out);
                boolean noAudioStream = out != null
                        && (out.toLowerCase(Locale.ROOT).contains("does not contain any stream")
                        || out.toLowerCase(Locale.ROOT).contains("output file is empty")
                        || out.toLowerCase(Locale.ROOT).contains("no audio stream"));
                throw new AudioProcessingException(
                        noAudioStream
                                ? "This video file doesn't appear to contain an audio track."
                                : "Could not extract audio from the uploaded video file.",
                        HttpStatus.UNPROCESSABLE_ENTITY);
            }
            if (Files.size(extractedPath) == 0) {
                throw new AudioProcessingException(
                        "The extracted audio track was empty. This video may not contain audio.",
                        HttpStatus.UNPROCESSABLE_ENTITY);
            }
            return extractedPath;
        } catch (IOException e) {
            throw new AudioProcessingException(
                    "Could not extract audio from the video (ffmpeg not available on the server).",
                    HttpStatus.INTERNAL_SERVER_ERROR, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (process != null) {
                process.destroyForcibly();
            }
            throw new AudioProcessingException(
                    "Audio extraction was interrupted or cancelled.", HttpStatus.INTERNAL_SERVER_ERROR, e);
        } finally {
            activeProcesses.remove(jobId);
        }
    }

    public boolean cancel(String jobId) {
        Process process = activeProcesses.remove(jobId);
        if (process != null && process.isAlive()) {
            log.info("[job {}] Terminating active FFmpeg extraction process", jobId);
            process.destroyForcibly();
            return true;
        }
        return false;
    }

    private String resolveFfmpeg() {
        String envFfmpeg = System.getenv("FFMPEG_PATH");
        if (envFfmpeg != null && !envFfmpeg.isBlank()) {
            return envFfmpeg.trim();
        }
        if (ffmpegExecutable != null && !ffmpegExecutable.isBlank()) {
            return ffmpegExecutable.trim();
        }
        return "ffmpeg";
    }
}