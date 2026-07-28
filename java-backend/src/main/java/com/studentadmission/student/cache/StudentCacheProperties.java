package com.studentadmission.student.cache;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Component
@ConfigurationProperties(prefix = "app.student-detail-cache")
public class StudentCacheProperties {

    private boolean enabled = true;
    private long ttlSeconds = 300;
    private long ttlJitterSeconds = 120;
    private long nullTtlSeconds = 30;
    private long secondEvictDelayMs = 1000;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public long getTtlSeconds() {
        return Math.max(1, ttlSeconds);
    }

    public void setTtlSeconds(long ttlSeconds) {
        this.ttlSeconds = ttlSeconds;
    }

    public long getTtlJitterSeconds() {
        return Math.max(0, ttlJitterSeconds);
    }

    public void setTtlJitterSeconds(long ttlJitterSeconds) {
        this.ttlJitterSeconds = ttlJitterSeconds;
    }

    public long getNullTtlSeconds() {
        return Math.max(1, nullTtlSeconds);
    }

    public void setNullTtlSeconds(long nullTtlSeconds) {
        this.nullTtlSeconds = nullTtlSeconds;
    }

    public long getSecondEvictDelayMs() {
        return Math.max(1, secondEvictDelayMs);
    }

    public void setSecondEvictDelayMs(long secondEvictDelayMs) {
        this.secondEvictDelayMs = secondEvictDelayMs;
    }
}
