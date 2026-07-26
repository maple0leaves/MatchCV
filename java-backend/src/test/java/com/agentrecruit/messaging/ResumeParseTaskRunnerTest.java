package com.agentrecruit.messaging;

import com.agentrecruit.candidate.ResumeParseProcessor;
import com.agentrecruit.messaging.entity.ResumeParseTask;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResumeParseTaskRunnerTest {

    private ResumeParseTaskService taskService;
    private ResumeParseProcessor processor;
    private ResumeParseTaskRunner runner;
    private ResumeParseTask task;

    @BeforeEach
    void setUp() {
        taskService = mock(ResumeParseTaskService.class);
        processor = mock(ResumeParseProcessor.class);
        runner = new ResumeParseTaskRunner(taskService, processor);
        task = new ResumeParseTask();
        task.setId(41L);
        task.setCandidateId(7L);
        task.setParseVersion(2);
        task.setConsumeAttempts(1);
    }

    @Test
    void duplicateDeliveryIsSkippedWhenTaskCannotBeClaimed() {
        when(taskService.claim(41L)).thenReturn(Optional.empty());

        runner.runFromMq(41L, false);

        verify(processor, never()).process(task);
        verify(taskService, never()).markSuccess(task);
    }

    @Test
    void successfulAttemptMarksTaskSuccess() {
        when(taskService.claim(41L)).thenReturn(Optional.of(task));

        runner.runFromMq(41L, false);

        verify(processor).process(task);
        verify(taskService).markSuccess(task);
    }

    @Test
    void retryableMqFailureReleasesTaskAndRequestsRedelivery() {
        when(taskService.claim(41L)).thenReturn(Optional.of(task));
        doThrow(new RetryableResumeParseException("AI timeout")).when(processor).process(task);

        assertThrows(IllegalStateException.class, () -> runner.runFromMq(41L, false));

        verify(taskService).releaseForMqRetry(task, "AI timeout");
        verify(taskService, never()).markDead(task, "AI timeout");
    }

    @Test
    void finalMqFailureMarksTaskDeadBeforeBrokerMovesItToDlq() {
        when(taskService.claim(41L)).thenReturn(Optional.of(task));
        doThrow(new RetryableResumeParseException("AI timeout")).when(processor).process(task);

        assertThrows(IllegalStateException.class, () -> runner.runFromMq(41L, true));

        verify(taskService).markDead(task, "AI timeout");
    }

    @Test
    void permanentFailureIsRecordedWithoutMqRetry() {
        when(taskService.claim(41L)).thenReturn(Optional.of(task));
        doThrow(new PermanentResumeParseException("file missing")).when(processor).process(task);

        runner.runFromMq(41L, false);

        verify(taskService).markFailed(task, "file missing");
        verify(taskService, never()).releaseForMqRetry(task, "file missing");
    }
}
