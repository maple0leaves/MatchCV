package com.studentadmission.student.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.Version;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("students")
public class Student {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long ownerUserId;
    @Version
    private Integer version;
    private String name;
    private String email;
    private String phone;
    private String skills;
    private String education;

    private String researchExperience;

    private String status;
    private String resumeFilePath;
    private String statusNote;
    private Integer parseVersion;
    private String parseStatus;
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private LocalDateTime parsedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
