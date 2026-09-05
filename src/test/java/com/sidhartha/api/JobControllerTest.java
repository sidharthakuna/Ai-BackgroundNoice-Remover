package com.sidhartha.api;

import com.sidhartha.dto.JobStatusResponse;
import com.sidhartha.exception.AudioProcessingException;
import com.sidhartha.job.AudioJobService;
import com.sidhartha.job.JobRecord;
import com.sidhartha.job.JobStatus;
import com.sidhartha.job.JobStatusStore;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import static org.junit.jupiter.api.Assertions.*;

class JobControllerTest {

    private JobStatusStore store;
    private AudioJobService jobService;
    private JobController controller;

    @BeforeEach
    void setUp() {
        store = new JobStatusStore();
        jobService = Mockito.mock(AudioJobService.class);
        controller = new JobController(store, jobService);
    }

    @Test
    void status_existingJob_returnsJobStatusResponse() {
        JobRecord record = new JobRecord("test-123", "podcast.mp3");
        record.markProgress(JobStatus.DENOISING, "Neural enhancement in progress", 70);
        record.setQueuePosition(0);
        store.put(record);

        ResponseEntity<JobStatusResponse> response = controller.status("test-123");
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals("test-123", response.getBody().jobId());
        assertEquals(JobStatus.DENOISING, response.getBody().status());
        assertEquals(70, response.getBody().progressPercentage());
        assertEquals(0, response.getBody().queuePosition());
    }

    @Test
    void status_nonExistentJob_throwsNotFound() {
        assertThrows(AudioProcessingException.class, () -> controller.status("non-existent"));
    }

    @Test
    void streamEvents_existingJob_returnsSseEmitter() {
        JobRecord record = new JobRecord("stream-123", "voice.wav");
        store.put(record);

        SseEmitter emitter = controller.streamEvents("stream-123");
        assertNotNull(emitter);
    }

    @Test
    void delete_existingJob_callsCancelAndRemovesFromStore() {
        JobRecord record = new JobRecord("del-123", "voice.wav");
        store.put(record);

        ResponseEntity<Void> response = controller.delete("del-123");
        assertEquals(HttpStatus.NO_CONTENT, response.getStatusCode());
        Mockito.verify(jobService).cancelJob("del-123");
        assertFalse(store.find("del-123").isPresent());
    }
}
