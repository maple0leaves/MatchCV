package com.studentadmission.messaging;

import com.studentadmission.student.ResumeParseProcessor;
import com.studentadmission.messaging.entity.ResumeParseTask;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Optional;

@Slf4j
@Component
public class ResumeParseTaskRunner {

    private final ResumeParseTaskService taskService;
    private final ResumeParseProcessor processor;

    public ResumeParseTaskRunner(ResumeParseTaskService taskService, ResumeParseProcessor processor) {
        this.taskService = taskService;
        this.processor = processor;
    }

    public void runFromMq(Long taskId, boolean finalAttempt) {
        Optional<ResumeParseTask> claimed = begin(taskId);
        if (claimed.isEmpty()) {
            return;
        }

        ResumeParseTask task = claimed.get();
        try {
            processor.process(task);
            taskService.markSuccess(task);
        } catch (PermanentResumeParseException e) {
            log.warn("简历解析任务不可重试，taskId={}: {}", taskId, e.getMessage());
            taskService.markFailed(task, e.getMessage());
        } catch (Exception e) {
            String message = safeMessage(e);
            if (finalAttempt) {
                taskService.markDead(task, message);
            } else {
                taskService.releaseForMqRetry(task, message);
            }
            throw new IllegalStateException("简历解析任务执行失败，等待 RocketMQ 重试", e);
        }
    }

    public void runLocally(Long taskId, int maxAttempts) {
        Optional<ResumeParseTask> claimed = begin(taskId);
        if (claimed.isEmpty()) {
            return;
        }

        ResumeParseTask task = claimed.get();
        try {
            processor.process(task);
            taskService.markSuccess(task);
        } catch (PermanentResumeParseException e) {
            log.warn("本地简历解析任务不可重试，taskId={}: {}", taskId, e.getMessage());
            taskService.markFailed(task, e.getMessage());
        } catch (Exception e) {
            String message = safeMessage(e);
            if (task.getConsumeAttempts() != null && task.getConsumeAttempts() >= maxAttempts) {
                taskService.markDead(task, message);
            } else {
                taskService.releaseForOutboxRetry(task, message);
            }
            log.warn("本地简历解析任务失败，taskId={}: {}", taskId, message);
        }
    }

    private Optional<ResumeParseTask> begin(Long taskId) {
        Optional<ResumeParseTask> claimed = taskService.claim(taskId);
        claimed.ifPresent(task -> taskService.updateStudentParseState(
                task, "parsing", "正在解析简历", false));
        return claimed;
    }

    private static String safeMessage(Exception e) {
        String message = e.getMessage();
        return message == null || message.isBlank() ? e.getClass().getSimpleName() : message;
    }
}
