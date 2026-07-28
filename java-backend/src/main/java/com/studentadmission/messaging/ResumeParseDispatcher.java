package com.studentadmission.messaging;

import com.studentadmission.messaging.entity.ResumeParseTask;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.task.TaskExecutor;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

import static com.studentadmission.messaging.ResumeParseTaskStates.PENDING;

@Slf4j
@Component
public class ResumeParseDispatcher {

    private final ResumeParseTaskService taskService;
    private final ResumeParseTaskRunner taskRunner;
    private final ObjectProvider<RocketMqResumeParseProducer> producerProvider;
    private final TaskExecutor localExecutor;
    private final int batchSize;
    private final int maxLocalAttempts;
    private final long staleMinutes;

    public ResumeParseDispatcher(
            ResumeParseTaskService taskService,
            ResumeParseTaskRunner taskRunner,
            ObjectProvider<RocketMqResumeParseProducer> producerProvider,
            @Qualifier("resumeParseExecutor") TaskExecutor localExecutor,
            @Value("${app.resume.outbox.batch-size:50}") int batchSize,
            @Value("${app.resume.local-max-attempts:3}") int maxLocalAttempts,
            @Value("${app.resume.processing-timeout-minutes:10}") long staleMinutes) {
        this.taskService = taskService;
        this.taskRunner = taskRunner;
        this.producerProvider = producerProvider;
        this.localExecutor = localExecutor;
        this.batchSize = batchSize;
        this.maxLocalAttempts = maxLocalAttempts;
        this.staleMinutes = staleMinutes;
    }

    public void dispatch(Long taskId) {
        ResumeParseTask task = taskService.get(taskId);
        if (task == null || !PENDING.equals(task.getTaskStatus())) {
            return;
        }

        RocketMqResumeParseProducer producer = producerProvider.getIfAvailable();
        if (producer != null && producer.publish(taskId)) {
            taskService.markMqSent(taskId);
            return;
        }

        int attempts = task.getDeliveryAttempts() == null ? 0 : task.getDeliveryAttempts();
        long delaySeconds = Math.min(60, 1L << Math.min(attempts, 6));
        taskService.markDeliveryFailed(
                taskId,
                producer == null ? "RocketMQ未启用，转入本地线程降级" : "RocketMQ投递失败，转入本地线程降级",
                LocalDateTime.now().plusSeconds(delaySeconds));
        submitLocal(taskId);
    }

    @Scheduled(fixedDelayString = "${app.resume.outbox.scan-interval-ms:5000}")
    public void publishPending() {
        List<ResumeParseTask> tasks = taskService.pendingDeliveries(batchSize);
        for (ResumeParseTask task : tasks) {
            dispatch(task.getId());
        }
    }

    @Scheduled(fixedDelayString = "${app.resume.outbox.recovery-interval-ms:60000}")
    public void recoverStaleTasks() {
        int recovered = taskService.recoverStaleProcessing(LocalDateTime.now().minusMinutes(staleMinutes));
        if (recovered > 0) {
            log.warn("已恢复 {} 个超时未完成的简历解析任务", recovered);
        }
    }

    private void submitLocal(Long taskId) {
        try {
            localExecutor.execute(() -> taskRunner.runLocally(taskId, maxLocalAttempts));
        } catch (TaskRejectedException e) {
            log.warn("本地简历解析线程池已满，任务保留在Outbox等待重试，taskId={}", taskId);
        }
    }
}
