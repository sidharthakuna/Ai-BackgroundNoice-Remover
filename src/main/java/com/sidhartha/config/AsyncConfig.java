package com.sidhartha.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.AsyncConfigurer;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;

/**
 * Explicit thread pool for AudioJobService's @Async runJob() method.
 *
 * WHY THIS IS NEEDED: @EnableAsync alone falls back to Spring's default
 * SimpleAsyncTaskExecutor, which spawns a brand-new thread per task
 * rather than pooling — fine for occasional short tasks, not appropriate
 * for a 15-minute audio pipeline that could be triggered by many
 * concurrent uploads. A bounded pool here means concurrent jobs beyond
 * the pool size queue up instead of spawning unbounded OS threads.
 *
 * Sizing: denoise jobs are CPU/GPU-bound (DeepFilterNet, optionally
 * Demucs), not I/O-bound, so a small pool close to available cores is
 * more appropriate than the large pool size you'd use for I/O-bound
 * async work. Tune corePoolSize/maxPoolSize to the server's actual core
 * count and expected concurrent-job load — the values below are a
 * starting point, not a measured optimum.
 *
 * @EnableScheduling is also declared here (rather than a separate
 * config class) because JobStatusStore's @Scheduled eviction method
 * needs it and this is the natural home for "background execution
 * infrastructure" as a single concern.
 */
@Configuration
@EnableAsync
@EnableScheduling
public class AsyncConfig implements AsyncConfigurer {

    @Override
    @Bean(name = "taskExecutor")
    public Executor getAsyncExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(4);
        executor.setQueueCapacity(20);
        executor.setThreadNamePrefix("audio-job-");
        executor.initialize();
        return executor;
    }
}