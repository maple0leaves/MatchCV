package com.agentrecruit.ai;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** 调用 Python AI 服务（服务间内部调用）。 */
@Slf4j
@Component
public class AiClient {

    private final WebClient aiWebClient;

    public AiClient(WebClient aiWebClient) {
        this.aiWebClient = aiWebClient;
    }

    /** 结构化解析的简历信息，对应 Python CandidateInfo。 */
    public record ParsedResume(String name, String email, List<String> skills,
                               String education, String summary,
                               String processing_warning) {
    }

    /**
     * 调用 Python /api/internal/parse-resume 把简历文本结构化为候选人信息。
     * 临时失败时抛出 AiServiceUnavailableException，由解析任务重试机制处理。
     */
    @SuppressWarnings("unchecked")
    public ParsedResume parseResume(String text) {
        try {
            Map<String, Object> body = aiWebClient.post()
                    .uri("/api/internal/parse-resume")
                    .bodyValue(Map.of("text", text))
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(60))
                    .block();
            if (body == null) {
                throw new AiServiceUnavailableException("AI 简历解析服务返回空响应");
            }
            List<String> skills = (List<String>) body.getOrDefault("skills", List.of());
            return new ParsedResume(
                    str(body.get("name")), str(body.get("email")), skills,
                    str(body.get("education")), str(body.get("summary")),
                    str(body.get("processing_warning")));
        } catch (AiServiceUnavailableException e) {
            throw e;
        } catch (Exception e) {
            log.warn("调用 AI 解析简历失败：{}", e.getMessage());
            throw new AiServiceUnavailableException("AI 简历解析服务暂不可用，请稍后重试");
        }
    }

    /**
     * 调用 Python /api/internal/ocr-resume 识别图片版简历（PNG/JPG）里的文字。
     * 识别结果仍然是纯文本，拿到后走跟 PDF 完全一样的下游流程（parseResume →
     * indexCandidate），本方法只负责"图片 → 文本"这一步。
     * 失败时返回 empty，调用方（ResumeParser）据此降级为空文本，走现有的
     * "未能提取到文字内容"兜底提示，不需要新增错误处理分支。
     */
    @SuppressWarnings("rawtypes")
    public Optional<String> ocrResume(byte[] imageBytes, String ext) {
        try {
            String base64 = Base64.getEncoder().encodeToString(imageBytes);
            String imageExt = ext == null ? "" : ext.replace(".", "");
            Map<String, Object> body = Map.of("image_base64", base64, "image_ext", imageExt);
            // Python 侧最坏情况下会依次尝试 1 个首选 + N 个候选 OCR 模型（见
            // config.py OCR_FALLBACK_MODELS），每个最多等 OCR_TIMEOUT_SECONDS 秒，
            // 这里的超时要覆盖那个最坏总时长再留缓冲，否则会在 Python 还没试完所有
            // 候选模型时就被这里提前掐断，抹掉"换模型重试"带来的成功率提升。
            Map response = aiWebClient.post()
                    .uri("/api/internal/ocr-resume")
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(170))
                    .block();
            if (response == null) {
                return Optional.empty();
            }
            String text = str(response.get("text"));
            return text.isBlank() ? Optional.empty() : Optional.of(text);
        } catch (WebClientResponseException e) {
            String body = e.getResponseBodyAsString();
            log.warn("调用 AI OCR 识别图片简历失败：{}", body);
            throw new AiServiceUnavailableException(friendlyServiceMessage(body));
        } catch (Exception e) {
            log.warn("调用 AI OCR 识别图片简历失败：{}", e.getMessage());
            throw new AiServiceUnavailableException("AI/OCR 服务暂不可用，请稍后重试");
        }
    }

    /** 解析成功后，把候选人简历文本同步到 Python 端 pgvector 向量库。 */
    @SuppressWarnings("rawtypes")
    public boolean indexCandidate(Long ownerUserId,
                                  Long candidateId,
                                  String name,
                                  String email,
                                  String skills,
                                  String education,
                                  String summary,
                                  String resumeText,
                                  String source) {
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("owner_user_id", ownerUserId);
            body.put("candidate_id", candidateId);
            body.put("name", str(name));
            body.put("email", str(email));
            body.put("skills", splitSkills(skills));
            body.put("education", str(education));
            body.put("summary", str(summary));
            body.put("resume_text", str(resumeText));
            body.put("source", str(source));

            Map response = aiWebClient.post()
                    .uri("/api/internal/index-candidate")
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(30))
                    .block();
            if (response == null) {
                return false;
            }
            Object indexed = response.get("indexed");
            return indexed instanceof Boolean value && value;
        } catch (Exception e) {
            log.warn("同步候选人到向量库失败，candidateId={}: {}", candidateId, e.getMessage());
            return false;
        }
    }

    /**
     * 删除候选人在 Python pgvector 中的所有向量块。
     * 失败时仅打 warn 日志，不抛出异常——向量删除是最终一致性操作，
     * 不应阻塞主业务（MySQL 删除已完成）。
     */
    @SuppressWarnings("rawtypes")
    public boolean unindexCandidate(Long ownerUserId, String source) {
        if (source == null || source.isBlank()) {
            return false;
        }
        try {
            Map response = aiWebClient.method(org.springframework.http.HttpMethod.DELETE)
                    .uri("/api/internal/delete-candidate")
                    .bodyValue(Map.of(
                            "owner_user_id", ownerUserId,
                            "source", source.strip()))
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(15))
                    .block();
            if (response == null) {
                return false;
            }
            Object deleted = response.get("deleted");
            return deleted instanceof Boolean value && value;
        } catch (Exception e) {
            log.warn("从向量库删除候选人失败，source={}: {}", source, e.getMessage());
            return false;
        }
    }

    @SuppressWarnings("rawtypes")
    public boolean syncVectorOwnership(List<Map<String, Object>> candidates) {
        try {
            Map response = aiWebClient.post()
                    .uri("/api/internal/sync-vector-ownership")
                    .bodyValue(Map.of("candidates", candidates))
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(30))
                    .block();
            return response != null;
        } catch (Exception e) {
            // 旧向量在 owner=0 下不会被任何用户检索到，因此同步失败不会造成越权；
            // 只影响旧候选人暂时无法参与智能匹配。
            log.warn("同步历史向量归属失败：{}", e.getMessage());
            return false;
        }
    }

    private static String str(Object o) {
        return o == null ? "" : o.toString();
    }

    private static List<String> splitSkills(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        List<String> skills = new ArrayList<>();
        for (String item : value.split("[,，;；/、]")) {
            String skill = item.strip();
            if (!skill.isEmpty()) {
                skills.add(skill);
            }
        }
        return skills;
    }

    private static String friendlyServiceMessage(String detail) {
        String value = str(detail).toLowerCase();
        if (value.contains("额度") || value.contains("quota") || value.contains("429")
                || value.contains("402") || value.contains("rate limit")) {
            return "AI/OCR 服务额度不足或请求过于频繁，请充值或稍后重试";
        }
        return "AI/OCR 服务暂不可用，请稍后重试";
    }

    public static class AiServiceUnavailableException extends RuntimeException {
        public AiServiceUnavailableException(String message) {
            super(message);
        }
    }
}
