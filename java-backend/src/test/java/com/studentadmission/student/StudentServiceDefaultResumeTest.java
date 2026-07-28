package com.studentadmission.student;

import com.studentadmission.ai.AiClient;
import com.studentadmission.student.cache.StudentDetailCache;
import com.studentadmission.student.entity.Student;
import com.studentadmission.student.mapper.StudentMapper;
import com.studentadmission.messaging.ResumeParseDispatcher;
import com.studentadmission.messaging.ResumeParseTaskService;
import com.studentadmission.messaging.entity.ResumeParseTask;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class StudentServiceDefaultResumeTest {

    @TempDir
    Path resumeDir;

    @Test
    void seedsTwoOwnedPdfStudentsAndDispatchesTheirParseTasks() throws Exception {
        StudentMapper mapper = mock(StudentMapper.class);
        ResumeParseTaskService taskService = mock(ResumeParseTaskService.class);
        ResumeParseDispatcher dispatcher = mock(ResumeParseDispatcher.class);
        StudentDetailCache detailCache = mock(StudentDetailCache.class);
        StudentService service = new StudentService(
                mapper,
                mock(AiClient.class),
                taskService,
                dispatcher,
                detailCache,
                resumeDir.toString());

        when(mapper.selectCount(any())).thenReturn(0L);
        AtomicLong sequence = new AtomicLong(10);
        when(taskService.createStudentAndTask(
                any(Student.class),
                any(Path.class),
                eq(".pdf"))).thenAnswer(invocation -> {
                    Student student = invocation.getArgument(0);
                    long id = sequence.incrementAndGet();
                    student.setId(id);
                    student.setVersion(0);
                    student.setParseVersion(1);
                    student.setParseStatus("pending");
                    ResumeParseTask task = new ResumeParseTask();
                    task.setId(1000L + id);
                    return new ResumeParseTaskService.StudentTask(student, task);
                });

        service.seedDefaultResumes(42L);

        ArgumentCaptor<Student> studentCaptor = ArgumentCaptor.forClass(Student.class);
        ArgumentCaptor<Path> pathCaptor = ArgumentCaptor.forClass(Path.class);
        verify(taskService, times(2)).createStudentAndTask(
                studentCaptor.capture(),
                pathCaptor.capture(),
                eq(".pdf"));

        List<Student> students = studentCaptor.getAllValues();
        assertThat(students).extracting(Student::getName)
                .containsExactly("林若辰", "周子轩");
        assertThat(students).extracting(Student::getOwnerUserId)
                .containsOnly(42L);
        assertThat(students).extracting(Student::getResumeFilePath)
                .containsExactly(
                        "data/resumes/42/default-lin-ruochen.pdf",
                        "data/resumes/42/default-zhou-zixuan.pdf");
        assertThat(students).extracting(Student::getParseStatus)
                .containsOnly("pending");

        for (Path path : pathCaptor.getAllValues()) {
            assertThat(path).startsWith(resumeDir.resolve("42"));
            assertThat(Files.readAllBytes(path)).startsWith("%PDF-".getBytes());
        }
        verify(dispatcher).dispatch(1011L);
        verify(dispatcher).dispatch(1012L);
    }

    @Test
    void skipsDefaultResumeWhenTheOwnedRecordAlreadyExists() {
        StudentMapper mapper = mock(StudentMapper.class);
        ResumeParseTaskService taskService = mock(ResumeParseTaskService.class);
        ResumeParseDispatcher dispatcher = mock(ResumeParseDispatcher.class);
        StudentService service = new StudentService(
                mapper,
                mock(AiClient.class),
                taskService,
                dispatcher,
                mock(StudentDetailCache.class),
                resumeDir.toString());

        when(mapper.selectCount(any())).thenReturn(1L);

        service.seedDefaultResumes(42L);

        verify(taskService, times(0)).createStudentAndTask(any(), any(), any());
        verify(dispatcher, times(0)).dispatch(any());
        assertThat(resumeDir.resolve("42")).doesNotExist();
    }
}
