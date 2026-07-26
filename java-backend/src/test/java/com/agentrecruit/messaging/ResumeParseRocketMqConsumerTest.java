package com.agentrecruit.messaging;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.rocketmq.common.message.MessageExt;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class ResumeParseRocketMqConsumerTest {

    @Test
    void marksOnlyTheLastBrokerAttemptAsFinal() {
        ResumeParseTaskRunner taskRunner = mock(ResumeParseTaskRunner.class);
        ResumeParseRocketMqConsumer consumer =
                new ResumeParseRocketMqConsumer(taskRunner, new ObjectMapper());

        consumer.onMessage(message(2));
        consumer.onMessage(message(3));

        verify(taskRunner).runFromMq(41L, false);
        verify(taskRunner).runFromMq(41L, true);
    }

    private static MessageExt message(int reconsumeTimes) {
        MessageExt message = new MessageExt();
        message.setBody("{\"taskId\":41}".getBytes(StandardCharsets.UTF_8));
        message.setReconsumeTimes(reconsumeTimes);
        return message;
    }
}
