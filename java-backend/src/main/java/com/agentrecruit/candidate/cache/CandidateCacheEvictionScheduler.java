package com.agentrecruit.candidate.cache;

import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

@Slf4j
@Component
public class CandidateCacheEvictionScheduler {

    private final ScheduledExecutorService executor =
            Executors.newSingleThreadScheduledExecutor(runnable -> {
                Thread thread = new Thread(runnable, "candidate-cache-evict-1");
                thread.setDaemon(true);
                return thread;
            });

    public void schedule(Runnable task, long delayMs) {
        try {
            executor.schedule(task, Math.max(1, delayMs), TimeUnit.MILLISECONDS);
        } catch (RejectedExecutionException e) {
            log.warn("候选人缓存延迟删除任务被拒绝");
        }
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdown();
        try {
            if (!executor.awaitTermination(3, TimeUnit.SECONDS)) {
                executor.shutdownNow();
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            executor.shutdownNow();
        }
    }
}
