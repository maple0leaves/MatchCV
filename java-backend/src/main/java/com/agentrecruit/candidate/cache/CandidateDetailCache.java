package com.agentrecruit.candidate.cache;

import com.agentrecruit.candidate.dto.CandidateResponse;
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
public class CandidateDetailCache {

    private static final String KEY_PREFIX = "matchcv:candidate:detail:v1:";
    private static final Set<String> CACHEABLE_PARSE_STATUS = Set.of("parsed", "failed");

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final CandidateCacheProperties properties;
    private final CandidateCacheEvictionScheduler evictionScheduler;

    public CandidateDetailCache(StringRedisTemplate redis,
                                ObjectMapper objectMapper,
                                CandidateCacheProperties properties,
                                CandidateCacheEvictionScheduler evictionScheduler) {
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

    public record Lookup(LookupState state, CandidateResponse candidate) {
        public static Lookup miss() {
            return new Lookup(LookupState.MISS, null);
        }

        public static Lookup found(CandidateResponse candidate) {
            return new Lookup(LookupState.FOUND, candidate);
        }

        public static Lookup notFound() {
            return new Lookup(LookupState.NOT_FOUND, null);
        }
    }

    public Lookup get(Long ownerUserId, Long candidateId) {
        if (!properties.isEnabled()) {
            return Lookup.miss();
        }

        String key = key(ownerUserId, candidateId);
        String value;
        try {
            value = redis.opsForValue().get(key);
        } catch (Exception e) {
            log.warn("读取候选人详情缓存失败，回源MySQL，ownerUserId={}，candidateId={}：{}",
                    ownerUserId, candidateId, safeMessage(e));
            return Lookup.miss();
        }
        if (!StringUtils.hasText(value)) {
            return Lookup.miss();
        }

        CachedCandidateDetail cached;
        try {
            cached = objectMapper.readValue(value, CachedCandidateDetail.class);
        } catch (Exception e) {
            log.warn("候选人详情缓存内容损坏，删除后回源MySQL，ownerUserId={}，candidateId={}",
                    ownerUserId, candidateId);
            deleteOnce(key, ownerUserId, candidateId);
            return Lookup.miss();
        }
        if (cached.schemaVersion() != CachedCandidateDetail.CURRENT_SCHEMA_VERSION) {
            deleteOnce(key, ownerUserId, candidateId);
            return Lookup.miss();
        }
        if (!cached.found()) {
            return Lookup.notFound();
        }
        if (cached.candidate() == null || !candidateId.equals(cached.candidate().id())) {
            deleteOnce(key, ownerUserId, candidateId);
            return Lookup.miss();
        }
        return Lookup.found(cached.candidate());
    }

    public void putIfStable(Long ownerUserId, Long candidateId, CandidateResponse candidate) {
        if (!properties.isEnabled()
                || candidate == null
                || !candidateId.equals(candidate.id())
                || !CACHEABLE_PARSE_STATUS.contains(candidate.parse_status())) {
            return;
        }

        long jitter = properties.getTtlJitterSeconds();
        long ttlSeconds = properties.getTtlSeconds()
                + (jitter == 0 ? 0 : ThreadLocalRandom.current().nextLong(jitter + 1));
        put(ownerUserId, candidateId, CachedCandidateDetail.found(candidate), ttlSeconds);
    }

    public void putNotFound(Long ownerUserId, Long candidateId) {
        if (!properties.isEnabled()) {
            return;
        }
        put(ownerUserId, candidateId, CachedCandidateDetail.notFound(), properties.getNullTtlSeconds());
    }

    public void evict(Long ownerUserId, Long candidateId) {
        if (!properties.isEnabled()) {
            return;
        }

        String key = key(ownerUserId, candidateId);
        deleteOnce(key, ownerUserId, candidateId);
        evictionScheduler.schedule(
                () -> deleteOnce(key, ownerUserId, candidateId),
                properties.getSecondEvictDelayMs());
    }

    String key(Long ownerUserId, Long candidateId) {
        return KEY_PREFIX + ownerUserId + ":" + candidateId;
    }

    private void put(Long ownerUserId,
                     Long candidateId,
                     CachedCandidateDetail value,
                     long ttlSeconds) {
        try {
            redis.opsForValue().set(
                    key(ownerUserId, candidateId),
                    objectMapper.writeValueAsString(value),
                    Duration.ofSeconds(Math.max(1, ttlSeconds)));
        } catch (Exception e) {
            log.warn("写入候选人详情缓存失败，忽略缓存，ownerUserId={}，candidateId={}：{}",
                    ownerUserId, candidateId, safeMessage(e));
        }
    }

    private void deleteOnce(String key, Long ownerUserId, Long candidateId) {
        try {
            redis.delete(key);
        } catch (Exception e) {
            log.warn("删除候选人详情缓存失败，等待TTL兜底，ownerUserId={}，candidateId={}：{}",
                    ownerUserId, candidateId, safeMessage(e));
        }
    }

    private static String safeMessage(Exception e) {
        String message = e.getMessage();
        return StringUtils.hasText(message) ? message : e.getClass().getSimpleName();
    }
}
