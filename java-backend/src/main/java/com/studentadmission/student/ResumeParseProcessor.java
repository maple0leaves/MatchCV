package com.studentadmission.student;

import com.studentadmission.ai.AiClient;
import com.studentadmission.student.cache.StudentDetailCache;
import com.studentadmission.student.entity.Student;
import com.studentadmission.student.mapper.StudentMapper;
import com.studentadmission.common.ApiException;
import com.studentadmission.messaging.PermanentResumeParseException;
import com.studentadmission.messaging.RetryableResumeParseException;
import com.studentadmission.messaging.entity.ResumeParseTask;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.Optional;

@Slf4j
@Component
public class ResumeParseProcessor {

    private final StudentMapper studentMapper;
    private final ResumeParser resumeParser;
    private final AiClient aiClient;
    private final StudentDetailCache detailCache;

    public ResumeParseProcessor(StudentMapper studentMapper,
                                ResumeParser resumeParser,
                                AiClient aiClient,
                                StudentDetailCache detailCache) {
        this.studentMapper = studentMapper;
        this.resumeParser = resumeParser;
        this.aiClient = aiClient;
        this.detailCache = detailCache;
    }

    public void process(ResumeParseTask task) {
        byte[] raw;
        try {
            raw = Files.readAllBytes(Path.of(task.getResumePath()));
        } catch (IOException | RuntimeException e) {
            throw new PermanentResumeParseException("读取简历文件失败：" + safeMessage(e), e);
        }

        String text;
        try {
            text = resumeParser.extractText(raw, task.getFileExt());
        } catch (AiClient.AiServiceUnavailableException e) {
            throw new RetryableResumeParseException(e.getMessage(), e);
        } catch (ApiException e) {
            throw new PermanentResumeParseException(e.getMessage(), e);
        }
        if (!StringUtils.hasText(text)) {
            throw new PermanentResumeParseException("未能从文件中提取到文字内容，请手动补充学生信息");
        }

        AiClient.ParsedResume parsed;
        try {
            parsed = aiClient.parseResume(text);
        } catch (AiClient.AiServiceUnavailableException e) {
            throw new RetryableResumeParseException(e.getMessage(), e);
        }

        Student student = studentMapper.selectById(task.getStudentId());
        if (student == null) {
            throw new PermanentResumeParseException("学生已删除，解析任务取消");
        }
        if (!task.getParseVersion().equals(Optional.ofNullable(student.getParseVersion()).orElse(0))) {
            throw new PermanentResumeParseException("解析任务版本已过期");
        }

        applyParsedResume(student, parsed);
        student.setParsedAt(LocalDateTime.now());
        student.setParseStatus("parsed");
        student.setStatusNote(StringUtils.hasText(parsed.processing_warning())
                ? parsed.processing_warning()
                : "简历解析完成");
        if (studentMapper.updateById(student) != 1) {
            throw new PermanentResumeParseException("学生简历解析期间被其他操作修改，请重新提交解析");
        }
        detailCache.evict(student.getOwnerUserId(), student.getId());

        boolean indexed = aiClient.indexStudent(
                student.getOwnerUserId(),
                student.getId(),
                student.getName(),
                student.getEmail(),
                student.getSkills(),
                student.getEducation(),
                student.getResearchExperience(),
                text,
                student.getResumeFilePath());
        if (!indexed) {
            String warning = "简历解析完成，但向量库同步失败，智能匹配暂时搜不到该学生，"
                    + "请稍后重新解析；若持续失败，请检查 LLM/Embedding 额度和 AI 服务状态";
            int updated = studentMapper.update(null, new LambdaUpdateWrapper<Student>()
                    .eq(Student::getId, task.getStudentId())
                    .eq(Student::getParseVersion, task.getParseVersion())
                    .set(Student::getStatusNote, warning));
            if (updated == 1) {
                detailCache.evict(student.getOwnerUserId(), student.getId());
            }
            log.warn("学生向量库同步失败，studentId={}", student.getId());
        }
    }

    private static void applyParsedResume(Student student, AiClient.ParsedResume parsed) {
        if (StringUtils.hasText(parsed.name())) {
            student.setName(parsed.name());
        }
        if (StringUtils.hasText(parsed.email())) {
            student.setEmail(parsed.email());
        }
        if (parsed.skills() != null && !parsed.skills().isEmpty()) {
            student.setSkills(String.join(", ", parsed.skills()));
        }
        if (StringUtils.hasText(parsed.education())) {
            student.setEducation(parsed.education());
        }
        if (StringUtils.hasText(parsed.summary())) {
            student.setResearchExperience(parsed.summary());
        } else {

            student.setResearchExperience("");
        }
    }

    private static String safeMessage(Exception e) {
        return StringUtils.hasText(e.getMessage()) ? e.getMessage() : e.getClass().getSimpleName();
    }
}
