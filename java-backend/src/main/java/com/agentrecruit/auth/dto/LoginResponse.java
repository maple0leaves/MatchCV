package com.agentrecruit.auth.dto;

public record LoginResponse(String access_token, String token_type, UserResponse user) {

    public static LoginResponse of(String accessToken, UserResponse user) {
        return new LoginResponse(accessToken, "bearer", user);
    }
}
