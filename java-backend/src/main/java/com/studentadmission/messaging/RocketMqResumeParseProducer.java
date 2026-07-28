package com.studentadmission.messaging;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.client.producer.SendResult;
import org.apache.rocketmq.client.producer.SendStatus;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@ConditionalOnProperty(name = "app.rocketmq.enabled", havingValue = "true", matchIfMissing = true)
public class RocketMqResumeParseProducer {

    private final RocketMQTemplate rocketMQTemplate;
    private final ObjectMapper objectMapper;
    private final String topic;
    private final long sendTimeoutMs;

    public RocketMqResumeParseProducer(RocketMQTemplate rocketMQTemplate,
                                       ObjectMapper objectMapper,
                                       @Value("${app.rocketmq.topics.resume-parse}") String topic,
                                       @Value("${rocketmq.producer.send-message-timeout:3000}") long sendTimeoutMs) {
        this.rocketMQTemplate = rocketMQTemplate;
        this.objectMapper = objectMapper;
        this.topic = topic;
        this.sendTimeoutMs = sendTimeoutMs;
    }

    public boolean publish(Long taskId) {
        try {
            ResumeParseMessage message = new ResumeParseMessage(taskId);
            SendResult result = rocketMQTemplate.syncSend(topic, toJson(message), sendTimeoutMs);
            boolean sent = result != null && result.getSendStatus() == SendStatus.SEND_OK;
            if (!sent) {
                log.warn("RocketMQ 未确认简历解析任务投递成功，taskId={}，sendStatus={}",
                        taskId, result == null ? "null" : result.getSendStatus());
            }
            return sent;
        } catch (Exception e) {
            log.warn("投递 RocketMQ 简历解析任务失败，taskId={}: {}", taskId, e.getMessage());
            return false;
        }
    }

    private String toJson(ResumeParseMessage message) throws JsonProcessingException {
        return objectMapper.writeValueAsString(message);
    }
}
