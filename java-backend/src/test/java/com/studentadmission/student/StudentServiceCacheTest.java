package com.studentadmission.student;

import com.studentadmission.ai.AiClient;
import com.studentadmission.student.cache.StudentDetailCache;
import com.studentadmission.student.dto.StudentResponse;
import com.studentadmission.student.dto.StudentUpdateRequest;
import com.studentadmission.student.entity.Student;
import com.studentadmission.student.mapper.StudentMapper;
import com.studentadmission.common.ApiException;
import com.studentadmission.messaging.ResumeParseDispatcher;
import com.studentadmission.messaging.ResumeParseTaskService;
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

class StudentServiceCacheTest {

    private StudentMapper mapper;
    private StudentDetailCache detailCache;
    private StudentService service;

    @BeforeEach
    void setUp() {
        mapper = mock(StudentMapper.class);
        detailCache = mock(StudentDetailCache.class);
        service = new StudentService(
                mapper,
                mock(AiClient.class),
                mock(ResumeParseTaskService.class),
                mock(ResumeParseDispatcher.class),
                detailCache,
                "data/resumes");
    }

    @Test
    void cacheHitDoesNotQueryMysql() {
        StudentResponse cached = response();
        when(detailCache.get(3L, 7L))
                .thenReturn(StudentDetailCache.Lookup.found(cached));

        StudentResponse actual = service.get(3L, 7L);

        assertEquals(cached, actual);
        verify(mapper, never()).selectOne(any());
    }

    @Test
    void cacheMissReadsMysqlAndCachesStableResponse() {
        Student student = student();
        when(detailCache.get(3L, 7L))
                .thenReturn(StudentDetailCache.Lookup.miss());
        when(mapper.selectOne(any())).thenReturn(student);

        StudentResponse actual = service.get(3L, 7L);

        assertEquals(7L, actual.id());
        verify(detailCache).putIfStable(3L, 7L, actual);
    }

    @Test
    void negativeCacheHitReturnsNotFoundWithoutMysql() {
        when(detailCache.get(3L, 404L))
                .thenReturn(StudentDetailCache.Lookup.notFound());

        ApiException error = assertThrows(ApiException.class, () -> service.get(3L, 404L));

        assertEquals(404, error.getStatusCode());
        verify(mapper, never()).selectOne(any());
    }

    @Test
    void missingMysqlStudentCreatesShortNegativeCacheEntry() {
        when(detailCache.get(3L, 404L))
                .thenReturn(StudentDetailCache.Lookup.miss());
        when(mapper.selectOne(any())).thenReturn(null);

        assertThrows(ApiException.class, () -> service.get(3L, 404L));

        verify(detailCache).putNotFound(3L, 404L);
    }

    @Test
    void successfulStudentUpdateEvictsCachedDetail() {
        Student student = student();
        when(mapper.selectOne(any())).thenReturn(student);
        when(mapper.updateById(student)).thenReturn(1);
        StudentUpdateRequest request =
                new StudentUpdateRequest("Bob", null, null, null, null, null);

        StudentResponse updated = service.update(3L, 7L, request);

        assertEquals("Bob", updated.name());
        verify(mapper, times(2)).selectOne(any());
        verify(detailCache).evict(3L, 7L);
    }

    private static Student student() {
        Student student = new Student();
        student.setId(7L);
        student.setOwnerUserId(3L);
        student.setVersion(1);
        student.setParseVersion(1);
        student.setParseStatus("parsed");
        student.setName("Alice");
        student.setEmail("alice@example.com");
        student.setPhone("13800000000");
        student.setSkills("Java");
        student.setEducation("本科");
        student.setResearchExperience("参与 Java 项目研究");
        student.setStatus("new");
        student.setResumeFilePath("data/resumes/3/resume.pdf");
        student.setStatusNote("解析完成");
        return student;
    }

    private static StudentResponse response() {
        return StudentResponse.from(student());
    }
}
