package com.agentrecruit.security;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;

/**
 * 基于 Redis 的 JWT 黑名单，实现无状态 JWT 的即时吊销（登出）。
 * key = "jwt:blacklist:" + token，TTL 设为 token 剩余有效期。
 */
@Component
public class JwtBlacklist {

    private static final String PREFIX = "jwt:blacklist:";

    private final StringRedisTemplate redis;

    public JwtBlacklist(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public void revoke(String token, long ttlSeconds) {
        if (ttlSeconds <= 0) {
            return;
        }
        redis.opsForValue().set(PREFIX + token, "1", Duration.ofSeconds(ttlSeconds));
    }

    public boolean isRevoked(String token) {
        return Boolean.TRUE.equals(redis.hasKey(PREFIX + token));
    }
}
