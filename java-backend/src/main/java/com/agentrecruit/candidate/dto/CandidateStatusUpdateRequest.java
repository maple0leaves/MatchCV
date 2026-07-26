package com.agentrecruit.candidate.dto;

import jakarta.validation.constraints.NotBlank;

public record CandidateStatusUpdateRequest(
        @NotBlank(message = "状态不能为空") String status,
        @NotBlank(message = "状态变更时备注为必填项") String status_note) {
}
