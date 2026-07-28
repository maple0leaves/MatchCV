package com.studentadmission.messaging;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.common.message.MessageExt;
import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;

@Slf4j
@Component
@ConditionalOnProperty(name = "app.rocketmq.enabled", havingValue = "true", matchIfMissing = true)
@RocketMQMessageListener(
        topic = "${app.rocketmq.topics.resume-parse}",
        consumerGroup = "${app.rocketmq.consumer-groups.resume-parse}",
        maxReconsumeTimes = 3,
        delayLevelWhenNextConsume = 2
)
public class ResumeParseRocketMqConsumer implements RocketMQListener<MessageExt> {

    private static final int MAX_RECONSUME_TIMES = 3;

    private final ResumeParseTaskRunner taskRunner;
    private final ObjectMapper objectMapper;

    public ResumeParseRocketMqConsumer(ResumeParseTaskRunner taskRunner, ObjectMapper objectMapper) {
        this.taskRunner = taskRunner;
        this.objectMapper = objectMapper;
    }

    @Override
    public void onMessage(MessageExt messageExt) {
        String payload = new String(messageExt.getBody(), StandardCharsets.UTF_8);
        try {
            ResumeParseMessage message = objectMapper.readValue(payload, ResumeParseMessage.class);
            if (message.taskId() == null) {
                log.warn("跳过非法简历解析消息：{}", payload);
                return;
            }



            boolean finalAttempt = messageExt.getReconsumeTimes() >= MAX_RECONSUME_TIMES;
            taskRunner.runFromMq(message.taskId(), finalAttempt);
        } catch (Exception e) {
            log.warn("消费简历解析消息失败：{}", e.getMessage(), e);
            throw new IllegalStateException("消费简历解析消息失败", e);
        }
    }
}
