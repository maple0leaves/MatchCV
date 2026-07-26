package com.agentrecruit.auth.dto;

public record CaptchaResponse(
        String captcha_id,
        String image,
        int expires_in_seconds) {
}
