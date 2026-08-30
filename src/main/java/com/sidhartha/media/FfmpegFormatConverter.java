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
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * Re-encodes the pipeline's wav output into the requested format (mp3/flac/ogg/m4a)
 * with studio-grade audio bitrate and encoding parameters.
 */
@Component
public class FfmpegFormatConverter {

    private static final Logger log = LoggerFactory.getLogger(FfmpegFormatConverter.class);

    @Value("${app.ffmpeg.path:ffmpeg}")
    private String ffmpegExecutable;

    private final Map<String, Process> activeProcesses = new ConcurrentHashMap<>();

    public Path convertOutputFormat(Path wavPath, Path jobDir, String format, String jobId) {
        Path convertedPath = jobDir.resolve("output." + format);
        String exec = resolveFfmpeg();

        List<String> cmd = new ArrayList<>(List.of(
                exec, "-nostdin", "-y", "-i", wavPath.toString()
        ));

        // Format-specific high-fidelity audio flags
        switch (format.toLowerCase()) {
            case "mp3" -> {
                cmd.add("-c:a");
                cmd.add("libmp3lame");
                cmd.add("-b:a");
                cmd.add("320k");
            }
            case "ogg" -> {
                cmd.add("-c:a");
                cmd.add("libvorbis");
                cmd.add("-q:a");
                cmd.add("7");
            }
            case "flac" -> {
                cmd.add("-c:a");
                cmd.add("flac");
                cmd.add("-compression_level");
                cmd.add("5");
            }
            case "m4a", "aac" -> {
                cmd.add("-c:a");
                cmd.add("aac");
                cmd.add("-b:a");
                cmd.add("256k");
            }
            default -> {
            }
        }

        cmd.add("-loglevel");
        cmd.add("error");
        cmd.add(convertedPath.toString());

        ProcessBuilder pb = new ProcessBuilder(cmd);
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

            boolean finished = process.waitFor(2, TimeUnit.MINUTES);
            if (!finished) {
                process.destroyForcibly();
                throw new AudioProcessingException(
                        "Converting to ." + format + " timed out.", HttpStatus.INTERNAL_SERVER_ERROR);
            }
            int exitCode = process.exitValue();
            String out = outputReader.getNow("");
            log.info("[job {}] ffmpeg convert to {} exit={}", jobId, format, exitCode);

            if (exitCode != 0 || !Files.exists(convertedPath)) {
                log.warn("[job {}] ffmpeg conversion failed, output:\n{}", jobId, out);
                throw new AudioProcessingException(
                        "Could not convert the result to ." + format + ". Try downloading as .wav instead.",
                        HttpStatus.INTERNAL_SERVER_ERROR);
            }
            return convertedPath;
        } catch (IOException e) {
            throw new AudioProcessingException(
                    "Could not convert the result to ." + format
                            + " (ffmpeg not available on the server). Try .wav instead.",
                    HttpStatus.INTERNAL_SERVER_ERROR, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (process != null) {
                process.destroyForcibly();
            }
            throw new AudioProcessingException(
                    "Conversion was interrupted or cancelled.", HttpStatus.INTERNAL_SERVER_ERROR, e);
        } finally {
            activeProcesses.remove(jobId);
        }
    }

    public boolean cancel(String jobId) {
        Process process = activeProcesses.remove(jobId);
        if (process != null && process.isAlive()) {
            log.info("[job {}] Terminating active FFmpeg conversion process", jobId);
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