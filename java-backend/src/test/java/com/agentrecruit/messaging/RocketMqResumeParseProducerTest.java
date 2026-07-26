package com.agentrecruit.messaging;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.rocketmq.client.producer.SendResult;
import org.apache.rocketmq.client.producer.SendStatus;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class RocketMqResumeParseProducerTest {

    @Test
    void acceptsOnlySendOkAsSuccessfulDelivery() {
        RocketMQTemplate template = mock(RocketMQTemplate.class);
        SendResult result = mock(SendResult.class);
        when(template.syncSend("resume-topic", "{\"taskId\":41}", 3000L)).thenReturn(result);
        RocketMqResumeParseProducer producer =
                new RocketMqResumeParseProducer(template, new ObjectMapper(), "resume-topic", 3000L);

        when(result.getSendStatus()).thenReturn(SendStatus.FLUSH_DISK_TIMEOUT);
        assertFalse(producer.publish(41L));

        when(result.getSendStatus()).thenReturn(SendStatus.SEND_OK);
        assertTrue(producer.publish(41L));
    }
}
