package com.agentrecruit.messaging.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("resume_parse_tasks")
public class ResumeParseTask {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long candidateId;
    private Long ownerUserId;
    private Integer parseVersion;
    private String resumePath;
    private String fileExt;
    private String taskStatus;
    private String mqStatus;
    private Integer deliveryAttempts;
    private Integer consumeAttempts;
    private LocalDateTime nextDeliveryAt;
    private String errorMessage;
    private LocalDateTime startedAt;
    private LocalDateTime completedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
