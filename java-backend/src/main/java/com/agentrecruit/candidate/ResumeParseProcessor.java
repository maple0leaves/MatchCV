package com.agentrecruit.candidate;

import com.agentrecruit.ai.AiClient;
import com.agentrecruit.candidate.cache.CandidateDetailCache;
import com.agentrecruit.candidate.entity.Candidate;
import com.agentrecruit.candidate.mapper.CandidateMapper;
import com.agentrecruit.common.ApiException;
import com.agentrecruit.messaging.PermanentResumeParseException;
import com.agentrecruit.messaging.RetryableResumeParseException;
import com.agentrecruit.messaging.entity.ResumeParseTask;
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

    private final CandidateMapper candidateMapper;
    private final ResumeParser resumeParser;
    private final AiClient aiClient;
    private final CandidateDetailCache detailCache;

    public ResumeParseProcessor(CandidateMapper candidateMapper,
                                ResumeParser resumeParser,
                                AiClient aiClient,
                                CandidateDetailCache detailCache) {
        this.candidateMapper = candidateMapper;
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

        Candidate candidate = candidateMapper.selectById(task.getCandidateId());
        if (candidate == null) {
            throw new PermanentResumeParseException("学生已删除，解析任务取消");
        }
        if (!task.getParseVersion().equals(Optional.ofNullable(candidate.getParseVersion()).orElse(0))) {
            throw new PermanentResumeParseException("解析任务版本已过期");
        }

        applyParsedResume(candidate, parsed);
        candidate.setParsedAt(LocalDateTime.now());
        candidate.setParseStatus("parsed");
        candidate.setStatusNote(StringUtils.hasText(parsed.processing_warning())
                ? parsed.processing_warning()
                : "简历解析完成");
        if (candidateMapper.updateById(candidate) != 1) {
            throw new PermanentResumeParseException("学生简历解析期间被其他操作修改，请重新提交解析");
        }
        detailCache.evict(candidate.getOwnerUserId(), candidate.getId());

        boolean indexed = aiClient.indexCandidate(
                candidate.getOwnerUserId(),
                candidate.getId(),
                candidate.getName(),
                candidate.getEmail(),
                candidate.getSkills(),
                candidate.getEducation(),
                candidate.getExperience(),
                text,
                candidate.getResumeFilePath());
        if (!indexed) {
            String warning = "简历解析完成，但向量库同步失败，智能匹配暂时搜不到该学生，"
                    + "请稍后重新解析；若持续失败，请检查 LLM/Embedding 额度和 AI 服务状态";
            int updated = candidateMapper.update(null, new LambdaUpdateWrapper<Candidate>()
                    .eq(Candidate::getId, task.getCandidateId())
                    .eq(Candidate::getParseVersion, task.getParseVersion())
                    .set(Candidate::getStatusNote, warning));
            if (updated == 1) {
                detailCache.evict(candidate.getOwnerUserId(), candidate.getId());
            }
            log.warn("候选人向量库同步失败，candidateId={}", candidate.getId());
        }
    }

    private static void applyParsedResume(Candidate candidate, AiClient.ParsedResume parsed) {
        if (StringUtils.hasText(parsed.name())) {
            candidate.setName(parsed.name());
        }
        if (StringUtils.hasText(parsed.email())) {
            candidate.setEmail(parsed.email());
        }
        if (parsed.skills() != null && !parsed.skills().isEmpty()) {
            candidate.setSkills(String.join(", ", parsed.skills()));
        }
        if (StringUtils.hasText(parsed.education())) {
            candidate.setEducation(parsed.education());
        }
        if (StringUtils.hasText(parsed.summary())) {
            candidate.setExperience(parsed.summary());
        } else {
            // 没有可靠摘要时清空旧兜底，避免继续展示过期解析内容。
            candidate.setExperience("");
        }
    }

    private static String safeMessage(Exception e) {
        return StringUtils.hasText(e.getMessage()) ? e.getMessage() : e.getClass().getSimpleName();
    }
}
