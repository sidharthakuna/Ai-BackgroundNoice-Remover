package com.sidhartha.denoise;

import com.sidhartha.exception.AudioProcessingException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * Runs the denoise pipeline (main.py) as a subprocess and interprets its exit code / stdout.
 * Includes multi-platform Python detection (Windows/Linux/macOS) and job cancellation.
 */
@Component
public class DenoiseProcessRunner {

    private static final Logger log = LoggerFactory.getLogger(DenoiseProcessRunner.class);
    private static final long PROCESS_TIMEOUT_MINUTES = 15;

    @Value("${app.python.executable:}")
    private String configuredPythonExecutable;

    private final Map<String, Process> activeProcesses = new ConcurrentHashMap<>();
    private volatile String cachedPythonExecutable;

    public void run(Path scriptDir, Path inputPath, Path outputPath, boolean useDemucs, String jobId) {
        run(scriptDir, inputPath, outputPath, useDemucs, "balanced", jobId, line -> { });
    }

    public void run(Path scriptDir, Path inputPath, Path outputPath, boolean useDemucs, String jobId,
                    Consumer<String> progressListener) {
        run(scriptDir, inputPath, outputPath, useDemucs, "balanced", jobId, progressListener);
    }

    public void run(Path scriptDir, Path inputPath, Path outputPath, boolean useDemucs, String mode, String jobId,
                    Consumer<String> progressListener) {
        Path entryPoint = scriptDir.resolve("main.py");
        String pythonExec = resolvePythonExecutable();
        List<String> command = new ArrayList<>(List.of(
                pythonExec,
                "-u",
                entryPoint.toString(),
                inputPath.toString(),
                outputPath.toString()
        ));
        if (useDemucs) {
            command.add("--demucs");
        }
        if (mode != null && !mode.isBlank()) {
            command.add("--mode");
            command.add(mode);
        }

        ProcessBuilder pb = new ProcessBuilder(command);
        pb.environment().put("PYTHONUNBUFFERED", "1");
        pb.directory(scriptDir.toFile());
        pb.redirectErrorStream(true);

        StringBuilder fullOutput = new StringBuilder();
        int exitCode;
        Process process = null;
        try {
            process = pb.start();
            activeProcesses.put(jobId, process);

            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    fullOutput.append(line).append('\n');
                    progressListener.accept(line);
                }
            }
            boolean finished = process.waitFor(PROCESS_TIMEOUT_MINUTES, TimeUnit.MINUTES);
            if (!finished) {
                process.destroyForcibly();
                throw new AudioProcessingException(
                        "Processing timed out after " + PROCESS_TIMEOUT_MINUTES + " minutes.",
                        HttpStatus.REQUEST_TIMEOUT);
            }
            exitCode = process.exitValue();
        } catch (IOException e) {
            throw new AudioProcessingException(
                    "Could not start the audio processing engine using '" + pythonExec + "'. Check Python installation.",
                    HttpStatus.INTERNAL_SERVER_ERROR, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (process != null) {
                process.destroyForcibly();
            }
            throw new AudioProcessingException(
                    "Processing was cancelled or interrupted.", HttpStatus.INTERNAL_SERVER_ERROR, e);
        } finally {
            activeProcesses.remove(jobId);
        }

        String scriptOutput = fullOutput.toString();
        log.info("[job {}] script exit={}", jobId, exitCode);
        if (log.isDebugEnabled()) {
            log.debug("[job {}] script output:\n{}", jobId, scriptOutput);
        }

        if (exitCode != 0) {
            throw new AudioProcessingException(
                    friendlyScriptError(scriptOutput), HttpStatus.UNPROCESSABLE_ENTITY);
        }
        if (!Files.exists(outputPath)) {
            throw new AudioProcessingException(
                    "Processing finished but produced no output file. The audio may be corrupt or unsupported.",
                    HttpStatus.UNPROCESSABLE_ENTITY);
        }
    }

    public boolean cancel(String jobId) {
        Process process = activeProcesses.remove(jobId);
        if (process != null && process.isAlive()) {
            log.info("[job {}] Terminating active Python process", jobId);
            process.destroyForcibly();
            return true;
        }
        return false;
    }

    private String friendlyScriptError(String scriptOutput) {
        if (scriptOutput == null) {
            return "Audio processing failed for an unknown reason.";
        }
        for (String line : scriptOutput.split("\\R")) {
            if (line.startsWith("ERROR:")) {
                return "Audio processing failed: " + line.substring("ERROR:".length()).trim();
            }
        }
        return "Audio processing failed. The file may be corrupt, empty, or in an unsupported format.";
    }

    public synchronized String resolvePythonExecutable() {
        if (cachedPythonExecutable != null) {
            return cachedPythonExecutable;
        }

        List<String> candidates = new ArrayList<>();

        // 1. Configured properties / environment variables
        if (configuredPythonExecutable != null && !configuredPythonExecutable.isBlank()) {
            candidates.add(configuredPythonExecutable.trim());
        }
        String envExec = System.getenv("PYTHON_EXECUTABLE");
        if (envExec != null && !envExec.isBlank()) {
            candidates.add(envExec.trim());
        }
        String propExec = System.getProperty("app.python.executable");
        if (propExec != null && !propExec.isBlank()) {
            candidates.add(propExec.trim());
        }

        // 2. Virtual environment paths
        boolean isWindows = System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");
        if (isWindows) {
            candidates.add(Path.of(".venv", "Scripts", "python.exe").toString());
            candidates.add(Path.of("venv", "Scripts", "python.exe").toString());
            candidates.add("python");
            candidates.add("py");
            candidates.add("python3");
        } else {
            candidates.add(Path.of(".venv", "bin", "python3").toString());
            candidates.add(Path.of(".venv", "bin", "python").toString());
            candidates.add(Path.of("venv", "bin", "python3").toString());
            candidates.add(Path.of("venv", "bin", "python").toString());
            candidates.add("python3");
            candidates.add("python");
        }

        for (String candidate : candidates) {
            if (testExecutable(candidate)) {
                log.info("Resolved active Python executable: {}", candidate);
                this.cachedPythonExecutable = candidate;
                return candidate;
            }
        }

        // Fallback default
        String fallback = isWindows ? "python" : "python3";
        this.cachedPythonExecutable = fallback;
        return fallback;
    }

    private boolean testExecutable(String exec) {
        if (exec == null || exec.isBlank()) {
            return false;
        }
        File file = new File(exec);
        if (file.isAbsolute() || exec.contains("/") || exec.contains("\\")) {
            if (!file.exists() || !file.canExecute()) {
                return false;
            }
        }
        try {
            Process process = new ProcessBuilder(exec, "-c", "import sys; print(sys.version_info[0])")
                    .redirectErrorStream(true)
                    .start();
            boolean finished = process.waitFor(3, TimeUnit.SECONDS);
            if (finished && process.exitValue() == 0) {
                try (BufferedReader r = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
                    String firstLine = r.readLine();
                    if (firstLine != null && firstLine.trim().startsWith("3")) {
                        return true;
                    }
                }
            } else {
                process.destroyForcibly();
            }
        } catch (Exception ignored) {
        }
        return false;
    }
}