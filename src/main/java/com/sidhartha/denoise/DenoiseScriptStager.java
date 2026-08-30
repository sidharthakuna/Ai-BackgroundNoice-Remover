package com.sidhartha.denoise;

import com.sidhartha.exception.AudioProcessingException;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/**
 * Stages the entire denoise/ Python module package (main.py plus its six
 * sibling modules — io_utils, vad_gate, denoise_dfn, dynamics, tone,
 * demucs_stage) from the classpath into a shared directory once at startup.
 */
@Component
public class DenoiseScriptStager {

    private static final Logger log = LoggerFactory.getLogger(DenoiseScriptStager.class);
    private Path sharedScriptDir;

    @PostConstruct
    public synchronized void init() {
        try {
            Path baseDir = Path.of(System.getProperty("java.io.tmpdir"), "denoise-pipeline-shared");
            Files.createDirectories(baseDir);
            extractModules(baseDir);
            this.sharedScriptDir = baseDir;
            log.info("Denoise Python modules staged successfully at {}", sharedScriptDir);
        } catch (Exception e) {
            log.error("Failed to stage denoise Python modules at startup", e);
        }
    }

    public synchronized Path stageInto(Path jobDir, String jobId) {
        if (sharedScriptDir != null && Files.exists(sharedScriptDir.resolve("main.py"))) {
            log.debug("[job {}] using shared denoise modules at {}", jobId, sharedScriptDir);
            return sharedScriptDir;
        }

        Path fallbackDir = jobDir.resolve("denoise");
        try {
            Files.createDirectories(fallbackDir);
            extractModules(fallbackDir);
            log.debug("[job {}] denoise modules staged at {}", jobId, fallbackDir);
            return fallbackDir;
        } catch (IOException e) {
            throw new AudioProcessingException(
                    "Internal error: could not load the processing script modules.",
                    HttpStatus.INTERNAL_SERVER_ERROR, e);
        }
    }

    private void extractModules(Path targetDir) throws IOException {
        var resolver = new PathMatchingResourcePatternResolver();
        Resource[] resources = resolver.getResources("classpath*:denoise/*.py");

        if (resources.length == 0) {
            throw new AudioProcessingException(
                    "Internal error: the denoise pipeline modules were not found on the classpath.",
                    HttpStatus.INTERNAL_SERVER_ERROR);
        }

        for (Resource resource : resources) {
            String filename = resource.getFilename();
            if (filename == null) {
                continue;
            }
            try (var in = resource.getInputStream()) {
                Files.copy(in, targetDir.resolve(filename), StandardCopyOption.REPLACE_EXISTING);
            }
        }

        if (!Files.exists(targetDir.resolve("main.py"))) {
            throw new AudioProcessingException(
                    "Internal error: main.py was not found among the denoise pipeline modules.",
                    HttpStatus.INTERNAL_SERVER_ERROR);
        }
    }
}