package com.studentadmission.student.dto;

import jakarta.validation.constraints.NotBlank;

public record StudentStatusUpdateRequest(
        @NotBlank(message = "状态不能为空") String status,
        @NotBlank(message = "状态变更时备注为必填项") String status_note) {
}
