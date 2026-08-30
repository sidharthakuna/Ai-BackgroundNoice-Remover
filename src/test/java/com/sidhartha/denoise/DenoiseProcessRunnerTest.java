package com.sidhartha.denoise;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class DenoiseProcessRunnerTest {

    private DenoiseProcessRunner runner;

    @BeforeEach
    void setUp() {
        runner = new DenoiseProcessRunner();
    }

    @Test
    void resolvePythonExecutable_returnsNonNullExecutable() {
        String exec = runner.resolvePythonExecutable();
        assertNotNull(exec);
        assertFalse(exec.isBlank());
    }

    @Test
    void cancel_nonExistentJob_returnsFalse() {
        assertFalse(runner.cancel("non-existent-job-id"));
    }
}
