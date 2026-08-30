package com.sidhartha.api;

import com.sidhartha.denoise.DenoiseProcessRunner;
import com.sidhartha.job.JobStatusStore;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class HealthControllerTest {

    private HealthController healthController;
    private DenoiseProcessRunner processRunner;
    private JobStatusStore jobStatusStore;

    @BeforeEach
    void setUp() {
        processRunner = new DenoiseProcessRunner();
        jobStatusStore = new JobStatusStore();
        healthController = new HealthController(processRunner, jobStatusStore);
    }

    @Test
    void health_returnsUpAndDetailedStatus() {
        Map<String, Object> result = healthController.health();
        assertNotNull(result);
        assertEquals("UP", result.get("status"));
        assertNotNull(result.get("timestamp"));
        assertTrue(result.containsKey("system"));
        assertTrue(result.containsKey("jobs"));
        assertTrue(result.containsKey("engines"));
    }
}
