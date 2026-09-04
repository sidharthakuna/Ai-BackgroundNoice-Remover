package com.sidhartha.denoise;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class DenoiseServiceClientTest {

    private DenoiseServiceClient client;

    @BeforeEach
    void setUp() {
        client = new DenoiseServiceClient();
    }

    @Test
    void isAvailable_whenDisabled_returnsFalse() {
        client.setServiceEnabled(false);
        assertFalse(client.isAvailable());
    }

    @Test
    void isAvailable_whenServerUnreachable_returnsFalseWithoutThrowing() {
        client.setServiceUrl("http://127.0.0.1:59999");
        assertFalse(client.isAvailable());
    }

    @Test
    void checkHealth_whenServerUnreachable_returnsFallbackMap() {
        client.setServiceUrl("http://127.0.0.1:59999");
        Map<String, Object> health = client.checkHealth();
        assertNotNull(health);
        assertEquals("UNAVAILABLE", health.get("status"));
    }

    @Test
    void cancel_whenServerUnreachable_returnsFalseWithoutThrowing() {
        client.setServiceUrl("http://127.0.0.1:59999");
        assertFalse(client.cancel("dummy-job-123"));
    }
}
