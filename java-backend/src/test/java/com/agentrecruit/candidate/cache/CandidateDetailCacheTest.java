package com.agentrecruit.candidate.cache;

import com.agentrecruit.candidate.dto.CandidateResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CandidateDetailCacheTest {

    private StringRedisTemplate redis;
    private ValueOperations<String, String> values;
    private CandidateCacheEvictionScheduler scheduler;
    private CandidateCacheProperties properties;
    private ObjectMapper objectMapper;
    private CandidateDetailCache cache;

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        values = mock(ValueOperations.class);
        scheduler = mock(CandidateCacheEvictionScheduler.class);
        properties = new CandidateCacheProperties();
        properties.setTtlSeconds(300);
        properties.setTtlJitterSeconds(0);
        properties.setNullTtlSeconds(30);
        properties.setSecondEvictDelayMs(1000);
        objectMapper = new ObjectMapper().findAndRegisterModules();
        when(redis.opsForValue()).thenReturn(values);
        cache = new CandidateDetailCache(redis, objectMapper, properties, scheduler);
    }

    @Test
    void readsAValidCandidateFromRedis() throws Exception {
        CandidateResponse response = response("parsed");
        when(values.get(cache.key(3L, 7L)))
                .thenReturn(objectMapper.writeValueAsString(CachedCandidateDetail.found(response)));

        CandidateDetailCache.Lookup lookup = cache.get(3L, 7L);

        assertEquals(CandidateDetailCache.LookupState.FOUND, lookup.state());
        assertEquals(response, lookup.candidate());
    }

    @Test
    void readsANegativeCacheMarkerWithoutCandidateData() throws Exception {
        when(values.get(cache.key(3L, 7L)))
                .thenReturn(objectMapper.writeValueAsString(CachedCandidateDetail.notFound()));

        CandidateDetailCache.Lookup lookup = cache.get(3L, 7L);

        assertEquals(CandidateDetailCache.LookupState.NOT_FOUND, lookup.state());
        assertNull(lookup.candidate());
    }

    @Test
    void cachesOnlyStableParseStates() {
        cache.putIfStable(3L, 7L, response("parsed"));
        cache.putIfStable(3L, 8L, responseWithId(8L, "failed"));
        cache.putIfStable(3L, 9L, responseWithId(9L, "pending"));
        cache.putIfStable(3L, 10L, responseWithId(10L, "parsing"));

        verify(values).set(eq(cache.key(3L, 7L)), any(String.class), eq(Duration.ofSeconds(300)));
        verify(values).set(eq(cache.key(3L, 8L)), any(String.class), eq(Duration.ofSeconds(300)));
        verify(values, never()).set(eq(cache.key(3L, 9L)), any(String.class), any(Duration.class));
        verify(values, never()).set(eq(cache.key(3L, 10L)), any(String.class), any(Duration.class));
    }

    @Test
    void usesShortTtlForNegativeCacheMarkers() {
        cache.putNotFound(3L, 404L);

        verify(values).set(
                eq(cache.key(3L, 404L)),
                any(String.class),
                eq(Duration.ofSeconds(30)));
    }

    @Test
    void redisReadFailureBecomesCacheMiss() {
        when(values.get(cache.key(3L, 7L))).thenThrow(new IllegalStateException("redis down"));

        CandidateDetailCache.Lookup lookup = cache.get(3L, 7L);

        assertEquals(CandidateDetailCache.LookupState.MISS, lookup.state());
    }

    @Test
    void redisWriteFailureDoesNotFailTheBusinessCall() {
        org.mockito.Mockito.doThrow(new IllegalStateException("redis down"))
                .when(values).set(anyString(), anyString(), any(Duration.class));

        assertDoesNotThrow(() -> cache.putIfStable(3L, 7L, response("parsed")));
    }

    @Test
    void redisDeleteFailureDoesNotFailTheBusinessCall() {
        when(redis.delete(cache.key(3L, 7L))).thenThrow(new IllegalStateException("redis down"));

        assertDoesNotThrow(() -> cache.evict(3L, 7L));
        verify(scheduler).schedule(any(Runnable.class), eq(1000L));
    }

    @Test
    void corruptedJsonIsDeletedAndBecomesCacheMiss() {
        when(values.get(cache.key(3L, 7L))).thenReturn("{broken-json");

        CandidateDetailCache.Lookup lookup = cache.get(3L, 7L);

        assertEquals(CandidateDetailCache.LookupState.MISS, lookup.state());
        verify(redis).delete(cache.key(3L, 7L));
    }

    @Test
    void evictionDeletesImmediatelyAndThenAgainAfterDelay() {
        doAnswer(invocation -> {
            ((Runnable) invocation.getArgument(0)).run();
            return null;
        }).when(scheduler).schedule(any(Runnable.class), eq(1000L));

        cache.evict(3L, 7L);

        verify(redis, times(2)).delete(cache.key(3L, 7L));
        verify(scheduler).schedule(any(Runnable.class), eq(1000L));
    }

    @Test
    void cacheKeyIsIsolatedByOwner() {
        assertNotEquals(cache.key(3L, 7L), cache.key(4L, 7L));
    }

    @Test
    void ttlJitterStaysInsideConfiguredRange() {
        properties.setTtlJitterSeconds(120);

        cache.putIfStable(3L, 7L, response("parsed"));

        verify(values).set(
                eq(cache.key(3L, 7L)),
                any(String.class),
                argThat(ttl -> !ttl.isNegative()
                        && ttl.compareTo(Duration.ofSeconds(300)) >= 0
                        && ttl.compareTo(Duration.ofSeconds(420)) <= 0));
    }

    @Test
    void disabledCacheDoesNotReadWriteOrScheduleEviction() {
        properties.setEnabled(false);

        assertEquals(CandidateDetailCache.LookupState.MISS, cache.get(3L, 7L).state());
        cache.putIfStable(3L, 7L, response("parsed"));
        cache.putNotFound(3L, 404L);
        cache.evict(3L, 7L);

        verify(values, never()).get(anyString());
        verify(values, never()).set(anyString(), anyString(), any(Duration.class));
        verify(redis, never()).delete(anyString());
        verify(scheduler, never()).schedule(any(Runnable.class), anyLong());
    }

    private static CandidateResponse response(String parseStatus) {
        return responseWithId(7L, parseStatus);
    }

    private static CandidateResponse responseWithId(Long id, String parseStatus) {
        return new CandidateResponse(
                id, "Alice", "alice@example.com", "13800000000", "Java",
                "本科", "参与 Java 项目研究", "new", "data/resumes/3/resume.pdf",
                "解析完成", parseStatus, null, null, null);
    }
}
