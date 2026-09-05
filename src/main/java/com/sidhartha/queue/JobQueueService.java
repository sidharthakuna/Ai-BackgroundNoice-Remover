package com.sidhartha.queue;

import com.sidhartha.job.JobRecord;
import com.sidhartha.job.JobStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Single-worker FIFO concurrency manager designed specifically for Render Free Tier (512MB RAM).
 * Ensures exactly one heavy AI/DSP job executes at a time, preventing container OOM kills,
 * while keeping queued jobs informed of their exact position in line.
 */
@Service
public class JobQueueService {

    private static final Logger log = LoggerFactory.getLogger(JobQueueService.class);

    private final Semaphore permit = new Semaphore(1, true);
    private final ConcurrentLinkedQueue<QueuedTask> waitingQueue = new ConcurrentLinkedQueue<>();
    private final ConcurrentHashMap<String, QueuedTask> registeredTasks = new ConcurrentHashMap<>();
    private final ExecutorService dispatcher = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "job-queue-dispatcher");
        t.setDaemon(true);
        return t;
    });

    private final AtomicBoolean running = new AtomicBoolean(true);
    private volatile String currentRunningJobId = null;

    public record QueuedTask(JobRecord record, Runnable task) {}

    public JobQueueService() {
        startDispatcher();
    }

    private void startDispatcher() {
        dispatcher.submit(() -> {
            while (running.get()) {
                try {
                    permit.acquire();
                    QueuedTask nextTask = waitingQueue.poll();
                    if (nextTask == null) {
                        permit.release();
                        Thread.sleep(50);
                        continue;
                    }

                    currentRunningJobId = nextTask.record().getJobId();
                    nextTask.record().setQueuePosition(0);
                    updatePositions();

                    // Execute task in virtual thread
                    Thread.ofVirtual().name("job-worker-" + currentRunningJobId).start(() -> {
                        try {
                            log.info("[queue] Starting processing for job {}", nextTask.record().getJobId());
                            nextTask.task().run();
                        } catch (Throwable t) {
                            log.error("[queue] Uncaught failure in job {}", nextTask.record().getJobId(), t);
                            nextTask.record().markFailed("Internal error during audio processing.", HttpStatus.INTERNAL_SERVER_ERROR);
                        } finally {
                            registeredTasks.remove(nextTask.record().getJobId());
                            currentRunningJobId = null;
                            permit.release();
                            updatePositions();
                        }
                    });

                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    break;
                } catch (Exception e) {
                    log.error("[queue] Error in dispatcher loop", e);
                }
            }
        });
    }

    /**
     * Submits a job to the FIFO queue.
     */
    public void submit(JobRecord record, Runnable task) {
        QueuedTask queuedTask = new QueuedTask(record, task);
        registeredTasks.put(record.getJobId(), queuedTask);
        waitingQueue.offer(queuedTask);
        updatePositions();
        log.info("[queue] Enqueued job {}. Position: {}", record.getJobId(), record.getQueuePosition());
    }

    /**
     * Cancels a job if it's waiting in the queue.
     */
    public boolean cancelIfQueued(String jobId) {
        QueuedTask task = registeredTasks.get(jobId);
        if (task != null && waitingQueue.remove(task)) {
            registeredTasks.remove(jobId);
            task.record().markFailed("Job was cancelled while waiting in queue.", HttpStatus.REQUEST_TIMEOUT);
            updatePositions();
            log.info("[queue] Cancelled queued job {}", jobId);
            return true;
        }
        return false;
    }

    public synchronized void updatePositions() {
        int pos = 1;
        for (QueuedTask item : waitingQueue) {
            item.record().setQueuePosition(pos++);
            item.record().markProgress(JobStatus.QUEUED, "Waiting in queue (position " + (pos - 1) + ")");
        }
    }

    public int getQueueDepth() {
        return waitingQueue.size();
    }

    public boolean isJobRunning() {
        return currentRunningJobId != null;
    }

    public String getCurrentRunningJobId() {
        return currentRunningJobId;
    }
}
