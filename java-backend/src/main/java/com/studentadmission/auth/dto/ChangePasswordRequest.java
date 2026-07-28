package com.studentadmission.auth.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record ChangePasswordRequest(
        @NotBlank(message = "原密码不能为空") String old_password,
        @NotBlank(message = "新密码不能为空")
        @Size(min = 8, max = 32, message = "新密码长度需为 8-32 位") String new_password) {
}
