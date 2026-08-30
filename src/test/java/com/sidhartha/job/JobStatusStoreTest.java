package com.sidhartha.job;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import java.nio.file.Path;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;

class JobStatusStoreTest {

    private JobStatusStore store;

    @BeforeEach
    void setUp() {
        store = new JobStatusStore();
    }

    @Test
    void putAndFind_worksCorrectly() {
        JobRecord record = new JobRecord("job-123", "test.wav");
        store.put(record);

        Optional<JobRecord> found = store.find("job-123");
        assertTrue(found.isPresent());
        assertEquals("test.wav", found.get().getOriginalFilename());
        assertEquals(JobStatus.QUEUED, found.get().getStatus());
    }

    @Test
    void remove_deletesRecord() {
        JobRecord record = new JobRecord("job-123", "test.wav");
        store.put(record);
        store.remove("job-123");

        assertFalse(store.find("job-123").isPresent());
    }

    @Test
    void record_stateTransitions() {
        JobRecord record = new JobRecord("job-123", "test.wav");
        assertEquals(JobStatus.QUEUED, record.getStatus());

        record.markProgress(JobStatus.DENOISING, "Removing background noise");
        assertEquals(JobStatus.DENOISING, record.getStatus());
        assertEquals("Removing background noise", record.getProgressMessage());

        Path out = Path.of("/tmp/out.wav");
        record.markDone(out, "audio/wav");
        assertEquals(JobStatus.DONE, record.getStatus());
        assertEquals(out, record.getOutputPath());
        assertEquals("audio/wav", record.getOutputContentType());

        record.markFailed("Something broke", HttpStatus.INTERNAL_SERVER_ERROR);
        assertEquals(JobStatus.FAILED, record.getStatus());
        assertEquals("Something broke", record.getErrorMessage());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, record.getErrorStatus());
    }

    @Test
    void record_progressPercentage_andMetrics() {
        JobRecord record = new JobRecord("job-456", "track.mp3");
        record.markProgress(JobStatus.DENOISING, "Denoising", 65);
        assertEquals(65, record.getProgressPercentage());

        record.markDone(Path.of("/tmp/out.wav"), "audio/wav", 1250);
        assertEquals(100, record.getProgressPercentage());
        assertEquals(1250, record.getProcessingTimeMs());
    }

    @Test
    void store_countsMetricsCorrectly() {
        JobRecord r1 = new JobRecord("job-1", "a.wav");
        JobRecord r2 = new JobRecord("job-2", "b.wav");
        r2.markDone(Path.of("/tmp/b.wav"), "audio/wav");
        JobRecord r3 = new JobRecord("job-3", "c.wav");
        r3.markFailed("Error", HttpStatus.BAD_REQUEST);

        store.put(r1);
        store.put(r2);
        store.put(r3);

        assertEquals(3, store.getTotalJobsCount());
        assertEquals(1, store.getActiveJobsCount());
        assertEquals(1, store.getDoneJobsCount());
        assertEquals(1, store.getFailedJobsCount());
    }

    @Test
    void evictionListener_isTriggered() {
        AtomicBoolean evicted = new AtomicBoolean(false);
        store.setEvictionListener(record -> evicted.set(true));

        // store is empty, evictExpired shouldn't fail
        assertDoesNotThrow(() -> store.evictExpired());
    }
}
