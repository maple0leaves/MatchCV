package com.studentadmission.security;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;





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
