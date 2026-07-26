package com.agentrecruit.candidate;

import com.agentrecruit.ai.AiClient;
import com.agentrecruit.candidate.cache.CandidateDetailCache;
import com.agentrecruit.candidate.dto.CandidateResponse;
import com.agentrecruit.candidate.dto.CandidateUpdateRequest;
import com.agentrecruit.candidate.entity.Candidate;
import com.agentrecruit.candidate.mapper.CandidateMapper;
import com.agentrecruit.common.ApiException;
import com.agentrecruit.messaging.ResumeParseDispatcher;
import com.agentrecruit.messaging.ResumeParseTaskService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CandidateServiceCacheTest {

    private CandidateMapper mapper;
    private CandidateDetailCache detailCache;
    private CandidateService service;

    @BeforeEach
    void setUp() {
        mapper = mock(CandidateMapper.class);
        detailCache = mock(CandidateDetailCache.class);
        service = new CandidateService(
                mapper,
                mock(AiClient.class),
                mock(ResumeParseTaskService.class),
                mock(ResumeParseDispatcher.class),
                detailCache,
                "data/resumes");
    }

    @Test
    void cacheHitDoesNotQueryMysql() {
        CandidateResponse cached = response();
        when(detailCache.get(3L, 7L))
                .thenReturn(CandidateDetailCache.Lookup.found(cached));

        CandidateResponse actual = service.get(3L, 7L);

        assertEquals(cached, actual);
        verify(mapper, never()).selectOne(any());
    }

    @Test
    void cacheMissReadsMysqlAndCachesStableResponse() {
        Candidate candidate = candidate();
        when(detailCache.get(3L, 7L))
                .thenReturn(CandidateDetailCache.Lookup.miss());
        when(mapper.selectOne(any())).thenReturn(candidate);

        CandidateResponse actual = service.get(3L, 7L);

        assertEquals(7L, actual.id());
        verify(detailCache).putIfStable(3L, 7L, actual);
    }

    @Test
    void negativeCacheHitReturnsNotFoundWithoutMysql() {
        when(detailCache.get(3L, 404L))
                .thenReturn(CandidateDetailCache.Lookup.notFound());

        ApiException error = assertThrows(ApiException.class, () -> service.get(3L, 404L));

        assertEquals(404, error.getStatusCode());
        verify(mapper, never()).selectOne(any());
    }

    @Test
    void missingMysqlCandidateCreatesShortNegativeCacheEntry() {
        when(detailCache.get(3L, 404L))
                .thenReturn(CandidateDetailCache.Lookup.miss());
        when(mapper.selectOne(any())).thenReturn(null);

        assertThrows(ApiException.class, () -> service.get(3L, 404L));

        verify(detailCache).putNotFound(3L, 404L);
    }

    @Test
    void successfulCandidateUpdateEvictsCachedDetail() {
        Candidate candidate = candidate();
        when(mapper.selectOne(any())).thenReturn(candidate);
        when(mapper.updateById(candidate)).thenReturn(1);
        CandidateUpdateRequest request =
                new CandidateUpdateRequest("Bob", null, null, null, null, null);

        CandidateResponse updated = service.update(3L, 7L, request);

        assertEquals("Bob", updated.name());
        verify(mapper, times(2)).selectOne(any());
        verify(detailCache).evict(3L, 7L);
    }

    private static Candidate candidate() {
        Candidate candidate = new Candidate();
        candidate.setId(7L);
        candidate.setOwnerUserId(3L);
        candidate.setVersion(1);
        candidate.setParseVersion(1);
        candidate.setParseStatus("parsed");
        candidate.setName("Alice");
        candidate.setEmail("alice@example.com");
        candidate.setPhone("13800000000");
        candidate.setSkills("Java");
        candidate.setEducation("本科");
        candidate.setExperience("参与 Java 项目研究");
        candidate.setStatus("new");
        candidate.setResumeFilePath("data/resumes/3/resume.pdf");
        candidate.setStatusNote("解析完成");
        return candidate;
    }

    private static CandidateResponse response() {
        return CandidateResponse.from(candidate());
    }
}
