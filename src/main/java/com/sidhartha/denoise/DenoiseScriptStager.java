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
 * Stages denoise scripts if classpath modules are packaged, or delegates
 * directly to the unified python_service module.
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
            if (extractModules(baseDir)) {
                this.sharedScriptDir = baseDir;
                log.info("Denoise Python modules staged successfully at {}", sharedScriptDir);
            } else {
                this.sharedScriptDir = Path.of(".");
                log.info("Using local python_service directory for fallback execution.");
            }
        } catch (Exception e) {
            log.debug("Fallback to local python_service directory: {}", e.getMessage());
            this.sharedScriptDir = Path.of(".");
        }
    }

    public synchronized Path stageInto(Path jobDir, String jobId) {
        if (sharedScriptDir != null) {
            return sharedScriptDir;
        }
        return Path.of(".");
    }

    private boolean extractModules(Path targetDir) {
        try {
            var resolver = new PathMatchingResourcePatternResolver();
            Resource[] resources = resolver.getResources("classpath*:denoise/*.py");

            if (resources.length == 0) {
                return false;
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
            return Files.exists(targetDir.resolve("main.py"));
        } catch (IOException e) {
            return false;
        }
    }
}