package com.sidhartha.queue;

import com.sidhartha.job.JobRecord;
import com.sidhartha.job.JobStatus;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;

class JobQueueServiceTest {

    private JobQueueService queueService;

    @BeforeEach
    void setUp() {
        queueService = new JobQueueService();
    }

    @Test
    void submit_singleJob_executesAndCompletes() throws InterruptedException {
        JobRecord record = new JobRecord("job-1", "test.wav");
        CountDownLatch latch = new CountDownLatch(1);
        AtomicBoolean executed = new AtomicBoolean(false);

        queueService.submit(record, () -> {
            executed.set(true);
            latch.countDown();
        });

        assertTrue(latch.await(3, TimeUnit.SECONDS), "Job should execute promptly");
        assertTrue(executed.get());
    }

    @Test
    void cancelIfQueued_waitingJob_cancelsSuccessfully() throws InterruptedException {
        JobRecord blockingRecord = new JobRecord("blocker", "test.wav");
        CountDownLatch blockLatch = new CountDownLatch(1);
        CountDownLatch finishLatch = new CountDownLatch(1);

        // Submit blocking job
        queueService.submit(blockingRecord, () -> {
            blockLatch.countDown();
            try {
                finishLatch.await(2, TimeUnit.SECONDS);
            } catch (InterruptedException ignored) {}
        });

        assertTrue(blockLatch.await(3, TimeUnit.SECONDS));

        // Submit second job that waits in queue
        JobRecord waitingRecord = new JobRecord("waiting", "test2.wav");
        queueService.submit(waitingRecord, () -> {});

        assertTrue(queueService.getQueueDepth() >= 1);
        assertTrue(waitingRecord.getQueuePosition() >= 1);

        // Cancel the waiting job
        boolean cancelled = queueService.cancelIfQueued("waiting");
        assertTrue(cancelled);
        assertEquals(JobStatus.FAILED, waitingRecord.getStatus());
        assertTrue(waitingRecord.getErrorMessage().contains("cancelled"));

        finishLatch.countDown();
    }
}
