package com.studentadmission.ai;

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


@Slf4j
@Component
public class AiClient {

    private final WebClient aiWebClient;

    public AiClient(WebClient aiWebClient) {
        this.aiWebClient = aiWebClient;
    }


    public record ParsedResume(String name, String email, List<String> skills,
                               String education, String summary,
                               String processing_warning) {
    }





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








    @SuppressWarnings("rawtypes")
    public Optional<String> ocrResume(byte[] imageBytes, String ext) {
        try {
            String base64 = Base64.getEncoder().encodeToString(imageBytes);
            String imageExt = ext == null ? "" : ext.replace(".", "");
            Map<String, Object> body = Map.of("image_base64", base64, "image_ext", imageExt);




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


    @SuppressWarnings("rawtypes")
    public boolean indexStudent(Long ownerUserId,
                                  Long studentId,
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
            body.put("student_id", studentId);
            body.put("name", str(name));
            body.put("email", str(email));
            body.put("skills", splitSkills(skills));
            body.put("education", str(education));
            body.put("summary", str(summary));
            body.put("resume_text", str(resumeText));
            body.put("source", str(source));

            Map response = aiWebClient.post()
                    .uri("/api/internal/index-student")
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
            log.warn("同步学生到向量库失败，studentId={}: {}", studentId, e.getMessage());
            return false;
        }
    }






    @SuppressWarnings("rawtypes")
    public boolean unindexStudent(Long ownerUserId, String source) {
        if (source == null || source.isBlank()) {
            return false;
        }
        try {
            Map response = aiWebClient.method(org.springframework.http.HttpMethod.DELETE)
                    .uri("/api/internal/delete-student")
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
            log.warn("从向量库删除学生失败，source={}: {}", source, e.getMessage());
            return false;
        }
    }

    @SuppressWarnings("rawtypes")
    public boolean syncVectorOwnership(List<Map<String, Object>> students) {
        try {
            Map response = aiWebClient.post()
                    .uri("/api/internal/sync-vector-ownership")
                    .bodyValue(Map.of("students", students))
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(30))
                    .block();
            return response != null;
        } catch (Exception e) {


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
