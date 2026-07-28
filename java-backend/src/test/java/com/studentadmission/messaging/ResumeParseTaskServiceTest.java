package com.studentadmission.messaging;

import com.studentadmission.student.cache.StudentDetailCache;
import com.studentadmission.student.entity.Student;
import com.studentadmission.student.mapper.StudentMapper;
import com.studentadmission.messaging.entity.ResumeParseTask;
import com.studentadmission.messaging.mapper.ResumeParseTaskMapper;
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
                Student.class);
    }

    @Test
    void claimReturnsEmptyWhenAnotherConsumerAlreadyChangedTheState() {
        StudentMapper studentMapper = mock(StudentMapper.class);
        ResumeParseTaskMapper taskMapper = mock(ResumeParseTaskMapper.class);
        StudentDetailCache detailCache = mock(StudentDetailCache.class);
        when(taskMapper.update(isNull(), any())).thenReturn(0);
        ResumeParseTaskService service =
                new ResumeParseTaskService(studentMapper, taskMapper, detailCache);

        Optional<ResumeParseTask> claimed = service.claim(99L);

        assertTrue(claimed.isEmpty());
        verify(taskMapper, never()).selectById(99L);
    }

    @Test
    void studentParseStateChangeEvictsStableDetailCache() {
        StudentMapper studentMapper = mock(StudentMapper.class);
        ResumeParseTaskMapper taskMapper = mock(ResumeParseTaskMapper.class);
        StudentDetailCache detailCache = mock(StudentDetailCache.class);
        when(studentMapper.update(isNull(), any())).thenReturn(1);
        ResumeParseTaskService service =
                new ResumeParseTaskService(studentMapper, taskMapper, detailCache);
        ResumeParseTask task = new ResumeParseTask();
        task.setStudentId(7L);
        task.setOwnerUserId(3L);
        task.setParseVersion(2);

        service.updateStudentParseState(task, "parsing", "正在解析简历", false);

        verify(detailCache).evict(3L, 7L);
    }
}
