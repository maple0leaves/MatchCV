package com.studentadmission.student;

import com.studentadmission.ai.AiClient;
import com.studentadmission.student.cache.StudentDetailCache;
import com.studentadmission.student.entity.Student;
import com.studentadmission.student.mapper.StudentMapper;
import com.studentadmission.messaging.PermanentResumeParseException;
import com.studentadmission.messaging.entity.ResumeParseTask;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResumeParseProcessorTest {

    @TempDir
    Path tempDir;

    @Test
    void successfulParseUsesOptimisticStudentUpdate() throws Exception {
        StudentMapper mapper = mock(StudentMapper.class);
        ResumeParser parser = mock(ResumeParser.class);
        AiClient aiClient = mock(AiClient.class);
        StudentDetailCache detailCache = mock(StudentDetailCache.class);
        ResumeParseProcessor processor = new ResumeParseProcessor(mapper, parser, aiClient, detailCache);
        ResumeParseTask task = task(Files.writeString(tempDir.resolve("resume.pdf"), "pdf"));
        Student student = student();

        when(parser.extractText(any(), any())).thenReturn("resume text");
        when(aiClient.parseResume("resume text")).thenReturn(parsed());
        when(mapper.selectById(7L)).thenReturn(student);
        when(mapper.updateById(student)).thenReturn(1);
        when(aiClient.indexStudent(any(), any(), any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(true);

        processor.process(task);

        assertEquals("parsed", student.getParseStatus());
        assertNotNull(student.getParsedAt());
        verify(mapper).updateById(student);
        verify(detailCache).evict(3L, 7L);
    }

    @Test
    void optimisticConflictStopsStaleResultFromBeingIndexed() throws Exception {
        StudentMapper mapper = mock(StudentMapper.class);
        ResumeParser parser = mock(ResumeParser.class);
        AiClient aiClient = mock(AiClient.class);
        StudentDetailCache detailCache = mock(StudentDetailCache.class);
        ResumeParseProcessor processor = new ResumeParseProcessor(mapper, parser, aiClient, detailCache);
        ResumeParseTask task = task(Files.writeString(tempDir.resolve("resume.pdf"), "pdf"));
        Student student = student();

        when(parser.extractText(any(), any())).thenReturn("resume text");
        when(aiClient.parseResume("resume text")).thenReturn(parsed());
        when(mapper.selectById(7L)).thenReturn(student);
        when(mapper.updateById(student)).thenReturn(0);

        assertThrows(PermanentResumeParseException.class, () -> processor.process(task));
    }

    private static ResumeParseTask task(Path path) {
        ResumeParseTask task = new ResumeParseTask();
        task.setId(1L);
        task.setStudentId(7L);
        task.setOwnerUserId(3L);
        task.setParseVersion(2);
        task.setResumePath(path.toString());
        task.setFileExt(".pdf");
        return task;
    }

    private static Student student() {
        Student student = new Student();
        student.setId(7L);
        student.setOwnerUserId(3L);
        student.setVersion(0);
        student.setParseVersion(2);
        student.setName("old");
        student.setEmail("");
        student.setSkills("");
        student.setEducation("");
        student.setResearchExperience("");
        student.setStatus("new");
        student.setResumeFilePath("data/resumes/3/resume.pdf");
        student.setStatusNote("正在解析");
        return student;
    }

    private static AiClient.ParsedResume parsed() {
        return new AiClient.ParsedResume(
                "Alice", "alice@example.com", List.of("Java"), "本科", "参与 Java 项目研究", "");
    }
}
