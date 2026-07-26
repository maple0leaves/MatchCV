package com.agentrecruit.messaging;

import com.agentrecruit.messaging.entity.ResumeParseTask;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.task.TaskExecutor;

import java.time.LocalDateTime;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResumeParseDispatcherTest {

    private ResumeParseTaskService taskService;
    private ResumeParseTaskRunner taskRunner;
    private ObjectProvider<RocketMqResumeParseProducer> producerProvider;
    private RocketMqResumeParseProducer producer;
    private TaskExecutor executor;
    private ResumeParseDispatcher dispatcher;
    private ResumeParseTask task;

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        taskService = mock(ResumeParseTaskService.class);
        taskRunner = mock(ResumeParseTaskRunner.class);
        producerProvider = mock(ObjectProvider.class);
        producer = mock(RocketMqResumeParseProducer.class);
        executor = mock(TaskExecutor.class);
        dispatcher = new ResumeParseDispatcher(
                taskService, taskRunner, producerProvider, executor, 50, 3, 10);

        task = new ResumeParseTask();
        task.setId(9L);
        task.setTaskStatus(ResumeParseTaskStates.PENDING);
        task.setDeliveryAttempts(0);
        when(taskService.get(9L)).thenReturn(task);
    }

    @Test
    void successfulMqPublishMarksOutboxSent() {
        when(producerProvider.getIfAvailable()).thenReturn(producer);
        when(producer.publish(9L)).thenReturn(true);

        dispatcher.dispatch(9L);

        verify(taskService).markMqSent(9L);
        verify(executor, never()).execute(any());
    }

    @Test
    void mqFailureKeepsOutboxPendingAndSubmitsLocalFallback() {
        when(producerProvider.getIfAvailable()).thenReturn(producer);
        when(producer.publish(9L)).thenReturn(false);

        dispatcher.dispatch(9L);

        verify(taskService).markDeliveryFailed(
                eq(9L), eq("RocketMQ投递失败，转入本地线程降级"), any(LocalDateTime.class));
        verify(executor).execute(any());
    }
}
