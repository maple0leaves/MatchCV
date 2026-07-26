package com.agentrecruit.candidate;

import com.agentrecruit.ai.AiClient;
import com.agentrecruit.candidate.cache.CandidateDetailCache;
import com.agentrecruit.candidate.entity.Candidate;
import com.agentrecruit.candidate.mapper.CandidateMapper;
import com.agentrecruit.messaging.PermanentResumeParseException;
import com.agentrecruit.messaging.entity.ResumeParseTask;
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
    void successfulParseUsesOptimisticCandidateUpdate() throws Exception {
        CandidateMapper mapper = mock(CandidateMapper.class);
        ResumeParser parser = mock(ResumeParser.class);
        AiClient aiClient = mock(AiClient.class);
        CandidateDetailCache detailCache = mock(CandidateDetailCache.class);
        ResumeParseProcessor processor = new ResumeParseProcessor(mapper, parser, aiClient, detailCache);
        ResumeParseTask task = task(Files.writeString(tempDir.resolve("resume.pdf"), "pdf"));
        Candidate candidate = candidate();

        when(parser.extractText(any(), any())).thenReturn("resume text");
        when(aiClient.parseResume("resume text")).thenReturn(parsed());
        when(mapper.selectById(7L)).thenReturn(candidate);
        when(mapper.updateById(candidate)).thenReturn(1);
        when(aiClient.indexCandidate(any(), any(), any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(true);

        processor.process(task);

        assertEquals("parsed", candidate.getParseStatus());
        assertNotNull(candidate.getParsedAt());
        verify(mapper).updateById(candidate);
        verify(detailCache).evict(3L, 7L);
    }

    @Test
    void optimisticConflictStopsStaleResultFromBeingIndexed() throws Exception {
        CandidateMapper mapper = mock(CandidateMapper.class);
        ResumeParser parser = mock(ResumeParser.class);
        AiClient aiClient = mock(AiClient.class);
        CandidateDetailCache detailCache = mock(CandidateDetailCache.class);
        ResumeParseProcessor processor = new ResumeParseProcessor(mapper, parser, aiClient, detailCache);
        ResumeParseTask task = task(Files.writeString(tempDir.resolve("resume.pdf"), "pdf"));
        Candidate candidate = candidate();

        when(parser.extractText(any(), any())).thenReturn("resume text");
        when(aiClient.parseResume("resume text")).thenReturn(parsed());
        when(mapper.selectById(7L)).thenReturn(candidate);
        when(mapper.updateById(candidate)).thenReturn(0);

        assertThrows(PermanentResumeParseException.class, () -> processor.process(task));
    }

    private static ResumeParseTask task(Path path) {
        ResumeParseTask task = new ResumeParseTask();
        task.setId(1L);
        task.setCandidateId(7L);
        task.setOwnerUserId(3L);
        task.setParseVersion(2);
        task.setResumePath(path.toString());
        task.setFileExt(".pdf");
        return task;
    }

    private static Candidate candidate() {
        Candidate candidate = new Candidate();
        candidate.setId(7L);
        candidate.setOwnerUserId(3L);
        candidate.setVersion(0);
        candidate.setParseVersion(2);
        candidate.setName("old");
        candidate.setEmail("");
        candidate.setSkills("");
        candidate.setEducation("");
        candidate.setExperience("");
        candidate.setStatus("new");
        candidate.setResumeFilePath("data/resumes/3/resume.pdf");
        candidate.setStatusNote("正在解析");
        return candidate;
    }

    private static AiClient.ParsedResume parsed() {
        return new AiClient.ParsedResume(
                "Alice", "alice@example.com", List.of("Java"), "本科", "参与 Java 项目研究", "");
    }
}
