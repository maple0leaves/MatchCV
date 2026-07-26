package com.agentrecruit.messaging;

import com.agentrecruit.candidate.cache.CandidateDetailCache;
import com.agentrecruit.candidate.entity.Candidate;
import com.agentrecruit.candidate.mapper.CandidateMapper;
import com.agentrecruit.messaging.entity.ResumeParseTask;
import com.agentrecruit.messaging.mapper.ResumeParseTaskMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResumeParseTaskServiceTest {

    @BeforeAll
    static void initializeMybatisMetadata() {
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""),
                ResumeParseTask.class);
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""),
                Candidate.class);
    }

    @Test
    void claimReturnsEmptyWhenAnotherConsumerAlreadyChangedTheState() {
        CandidateMapper candidateMapper = mock(CandidateMapper.class);
        ResumeParseTaskMapper taskMapper = mock(ResumeParseTaskMapper.class);
        CandidateDetailCache detailCache = mock(CandidateDetailCache.class);
        when(taskMapper.update(isNull(), any())).thenReturn(0);
        ResumeParseTaskService service =
                new ResumeParseTaskService(candidateMapper, taskMapper, detailCache);

        Optional<ResumeParseTask> claimed = service.claim(99L);

        assertTrue(claimed.isEmpty());
        verify(taskMapper, never()).selectById(99L);
    }

    @Test
    void candidateParseStateChangeEvictsStableDetailCache() {
        CandidateMapper candidateMapper = mock(CandidateMapper.class);
        ResumeParseTaskMapper taskMapper = mock(ResumeParseTaskMapper.class);
        CandidateDetailCache detailCache = mock(CandidateDetailCache.class);
        when(candidateMapper.update(isNull(), any())).thenReturn(1);
        ResumeParseTaskService service =
                new ResumeParseTaskService(candidateMapper, taskMapper, detailCache);
        ResumeParseTask task = new ResumeParseTask();
        task.setCandidateId(7L);
        task.setOwnerUserId(3L);
        task.setParseVersion(2);

        service.updateCandidateParseState(task, "parsing", "正在解析简历", false);

        verify(detailCache).evict(3L, 7L);
    }
}
