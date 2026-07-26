package com.agentrecruit.auth;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;

/** 基于 Redis 的登录失败限流，防暴力破解。 */
@Component
public class LoginRateLimiter {

    private static final String PREFIX = "login:fail:";

    private final StringRedisTemplate redis;
    private final int maxFail;
    private final long blockMinutes;

    public LoginRateLimiter(
            StringRedisTemplate redis,
            @Value("${app.login.max-fail}") int maxFail,
            @Value("${app.login.block-minutes}") long blockMinutes) {
        this.redis = redis;
        this.maxFail = maxFail;
        this.blockMinutes = blockMinutes;
    }

    public boolean isBlocked(String username) {
        String value = redis.opsForValue().get(PREFIX + username);
        return value != null && Integer.parseInt(value) >= maxFail;
    }

    public void recordFailure(String username) {
        String key = PREFIX + username;
        Long count = redis.opsForValue().increment(key);
        if (count != null && count == 1L) {
            redis.expire(key, Duration.ofMinutes(blockMinutes));
        }
    }

    public void reset(String username) {
        redis.delete(PREFIX + username);
    }
}
