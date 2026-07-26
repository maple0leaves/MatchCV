package com.agentrecruit.ai;

import com.agentrecruit.candidate.entity.Candidate;
import com.agentrecruit.candidate.mapper.CandidateMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * V3 把历史候选人归给历史管理员后，把同一归属同步到旧 pgvector 行。
 * 新上传数据会在写向量时直接携带 owner_user_id。
 */
@Slf4j
@Order(100)
@Component
public class VectorOwnershipInitializer implements ApplicationRunner {

    private final CandidateMapper candidateMapper;
    private final AiClient aiClient;

    public VectorOwnershipInitializer(CandidateMapper candidateMapper, AiClient aiClient) {
        this.candidateMapper = candidateMapper;
        this.aiClient = aiClient;
    }

    @Override
    public void run(ApplicationArguments args) {
        List<Map<String, Object>> mappings = candidateMapper.selectList(null).stream()
                .filter(candidate -> candidate.getOwnerUserId() != null)
                .filter(candidate -> StringUtils.hasText(candidate.getResumeFilePath()))
                .map(this::toMapping)
                .toList();
        if (!mappings.isEmpty() && !aiClient.syncVectorOwnership(mappings)) {
            log.warn("历史候选人向量归属尚未同步；旧数据需重新解析后才能参与智能匹配");
        }
    }

    private Map<String, Object> toMapping(Candidate candidate) {
        Map<String, Object> mapping = new LinkedHashMap<>();
        mapping.put("owner_user_id", candidate.getOwnerUserId());
        mapping.put("source", candidate.getResumeFilePath());
        return mapping;
    }
}
