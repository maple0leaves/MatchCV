package com.agentrecruit.auth.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
        @NotBlank(message = "用户名不能为空") @Size(min = 2, max = 100, message = "用户名至少 2 个字符") String username,
        @NotBlank(message = "密码不能为空") @Size(min = 8, max = 32, message = "密码长度需为 8-32 位") String password,
        @Size(max = 50, message = "昵称最多 50 个字符") String nickname,
        @NotBlank(message = "验证码标识不能为空") @Size(max = 64, message = "验证码标识无效") String captcha_id,
        @NotBlank(message = "请输入验证码") @Size(min = 4, max = 8, message = "验证码格式不正确") String captcha_code) {
}
