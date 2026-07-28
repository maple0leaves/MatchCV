package com.studentadmission.student.cache;

import com.studentadmission.student.dto.StudentResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.time.Duration;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

@Slf4j
@Component
public class StudentDetailCache {

    private static final String KEY_PREFIX = "matchcv:student:detail:v1:";
    private static final Set<String> CACHEABLE_PARSE_STATUS = Set.of("parsed", "failed");

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final StudentCacheProperties properties;
    private final StudentCacheEvictionScheduler evictionScheduler;

    public StudentDetailCache(StringRedisTemplate redis,
                                ObjectMapper objectMapper,
                                StudentCacheProperties properties,
                                StudentCacheEvictionScheduler evictionScheduler) {
        this.redis = redis;
        this.objectMapper = objectMapper;
        this.properties = properties;
        this.evictionScheduler = evictionScheduler;
    }

    public enum LookupState {
        MISS,
        FOUND,
        NOT_FOUND
    }

    public record Lookup(LookupState state, StudentResponse student) {
        public static Lookup miss() {
            return new Lookup(LookupState.MISS, null);
        }

        public static Lookup found(StudentResponse student) {
            return new Lookup(LookupState.FOUND, student);
        }

        public static Lookup notFound() {
            return new Lookup(LookupState.NOT_FOUND, null);
        }
    }

    public Lookup get(Long ownerUserId, Long studentId) {
        if (!properties.isEnabled()) {
            return Lookup.miss();
        }

        String key = key(ownerUserId, studentId);
        String value;
        try {
            value = redis.opsForValue().get(key);
        } catch (Exception e) {
            log.warn("读取学生详情缓存失败，回源MySQL，ownerUserId={}，studentId={}：{}",
                    ownerUserId, studentId, safeMessage(e));
            return Lookup.miss();
        }
        if (!StringUtils.hasText(value)) {
            return Lookup.miss();
        }

        CachedStudentDetail cached;
        try {
            cached = objectMapper.readValue(value, CachedStudentDetail.class);
        } catch (Exception e) {
            log.warn("学生详情缓存内容损坏，删除后回源MySQL，ownerUserId={}，studentId={}",
                    ownerUserId, studentId);
            deleteOnce(key, ownerUserId, studentId);
            return Lookup.miss();
        }
        if (cached.schemaVersion() != CachedStudentDetail.CURRENT_SCHEMA_VERSION) {
            deleteOnce(key, ownerUserId, studentId);
            return Lookup.miss();
        }
        if (!cached.found()) {
            return Lookup.notFound();
        }
        if (cached.student() == null || !studentId.equals(cached.student().id())) {
            deleteOnce(key, ownerUserId, studentId);
            return Lookup.miss();
        }
        return Lookup.found(cached.student());
    }

    public void putIfStable(Long ownerUserId, Long studentId, StudentResponse student) {
        if (!properties.isEnabled()
                || student == null
                || !studentId.equals(student.id())
                || !CACHEABLE_PARSE_STATUS.contains(student.parse_status())) {
            return;
        }

        long jitter = properties.getTtlJitterSeconds();
        long ttlSeconds = properties.getTtlSeconds()
                + (jitter == 0 ? 0 : ThreadLocalRandom.current().nextLong(jitter + 1));
        put(ownerUserId, studentId, CachedStudentDetail.found(student), ttlSeconds);
    }

    public void putNotFound(Long ownerUserId, Long studentId) {
        if (!properties.isEnabled()) {
            return;
        }
        put(ownerUserId, studentId, CachedStudentDetail.notFound(), properties.getNullTtlSeconds());
    }

    public void evict(Long ownerUserId, Long studentId) {
        if (!properties.isEnabled()) {
            return;
        }

        String key = key(ownerUserId, studentId);
        deleteOnce(key, ownerUserId, studentId);
        evictionScheduler.schedule(
                () -> deleteOnce(key, ownerUserId, studentId),
                properties.getSecondEvictDelayMs());
    }

    String key(Long ownerUserId, Long studentId) {
        return KEY_PREFIX + ownerUserId + ":" + studentId;
    }

    private void put(Long ownerUserId,
                     Long studentId,
                     CachedStudentDetail value,
                     long ttlSeconds) {
        try {
            redis.opsForValue().set(
                    key(ownerUserId, studentId),
                    objectMapper.writeValueAsString(value),
                    Duration.ofSeconds(Math.max(1, ttlSeconds)));
        } catch (Exception e) {
            log.warn("写入学生详情缓存失败，忽略缓存，ownerUserId={}，studentId={}：{}",
                    ownerUserId, studentId, safeMessage(e));
        }
    }

    private void deleteOnce(String key, Long ownerUserId, Long studentId) {
        try {
            redis.delete(key);
        } catch (Exception e) {
            log.warn("删除学生详情缓存失败，等待TTL兜底，ownerUserId={}，studentId={}：{}",
                    ownerUserId, studentId, safeMessage(e));
        }
    }

    private static String safeMessage(Exception e) {
        String message = e.getMessage();
        return StringUtils.hasText(message) ? message : e.getClass().getSimpleName();
    }
}
