package com.agentrecruit.candidate;

import com.agentrecruit.ai.AiClient;
import com.agentrecruit.candidate.cache.CandidateDetailCache;
import com.agentrecruit.candidate.entity.Candidate;
import com.agentrecruit.candidate.mapper.CandidateMapper;
import com.agentrecruit.messaging.ResumeParseDispatcher;
import com.agentrecruit.messaging.ResumeParseTaskService;
import com.agentrecruit.messaging.entity.ResumeParseTask;
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

class CandidateServiceDefaultResumeTest {

    @TempDir
    Path resumeDir;

    @Test
    void seedsTwoOwnedPdfCandidatesAndDispatchesTheirParseTasks() throws Exception {
        CandidateMapper mapper = mock(CandidateMapper.class);
        ResumeParseTaskService taskService = mock(ResumeParseTaskService.class);
        ResumeParseDispatcher dispatcher = mock(ResumeParseDispatcher.class);
        CandidateDetailCache detailCache = mock(CandidateDetailCache.class);
        CandidateService service = new CandidateService(
                mapper,
                mock(AiClient.class),
                taskService,
                dispatcher,
                detailCache,
                resumeDir.toString());

        when(mapper.selectCount(any())).thenReturn(0L);
        AtomicLong sequence = new AtomicLong(10);
        when(taskService.createCandidateAndTask(
                any(Candidate.class),
                any(Path.class),
                eq(".pdf"))).thenAnswer(invocation -> {
                    Candidate candidate = invocation.getArgument(0);
                    long id = sequence.incrementAndGet();
                    candidate.setId(id);
                    candidate.setVersion(0);
                    candidate.setParseVersion(1);
                    candidate.setParseStatus("pending");
                    ResumeParseTask task = new ResumeParseTask();
                    task.setId(1000L + id);
                    return new ResumeParseTaskService.CandidateTask(candidate, task);
                });

        service.seedDefaultResumes(42L);

        ArgumentCaptor<Candidate> candidateCaptor = ArgumentCaptor.forClass(Candidate.class);
        ArgumentCaptor<Path> pathCaptor = ArgumentCaptor.forClass(Path.class);
        verify(taskService, times(2)).createCandidateAndTask(
                candidateCaptor.capture(),
                pathCaptor.capture(),
                eq(".pdf"));

        List<Candidate> candidates = candidateCaptor.getAllValues();
        assertThat(candidates).extracting(Candidate::getName)
                .containsExactly("林若辰", "周子轩");
        assertThat(candidates).extracting(Candidate::getOwnerUserId)
                .containsOnly(42L);
        assertThat(candidates).extracting(Candidate::getResumeFilePath)
                .containsExactly(
                        "data/resumes/42/default-lin-ruochen.pdf",
                        "data/resumes/42/default-zhou-zixuan.pdf");
        assertThat(candidates).extracting(Candidate::getParseStatus)
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
        CandidateMapper mapper = mock(CandidateMapper.class);
        ResumeParseTaskService taskService = mock(ResumeParseTaskService.class);
        ResumeParseDispatcher dispatcher = mock(ResumeParseDispatcher.class);
        CandidateService service = new CandidateService(
                mapper,
                mock(AiClient.class),
                taskService,
                dispatcher,
                mock(CandidateDetailCache.class),
                resumeDir.toString());

        when(mapper.selectCount(any())).thenReturn(1L);

        service.seedDefaultResumes(42L);

        verify(taskService, times(0)).createCandidateAndTask(any(), any(), any());
        verify(dispatcher, times(0)).dispatch(any());
        assertThat(resumeDir.resolve("42")).doesNotExist();
    }
}
