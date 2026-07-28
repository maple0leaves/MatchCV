package com.studentadmission.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.TimeoutException;
import java.util.function.Consumer;






@Slf4j
@RestController
public class AiProxyController {
    private static final ObjectMapper MAPPER = new ObjectMapper();






    private static final Duration ADMISSION_PROXY_TIMEOUT = Duration.ofSeconds(100);

    private final WebClient aiWebClient;

    public AiProxyController(WebClient aiWebClient) {
        this.aiWebClient = aiWebClient;
    }

    @PostMapping("/api/admission")
    public ResponseEntity<byte[]> admission(@RequestBody(required = false) byte[] body, HttpServletRequest req) {
        return forwardJson(HttpMethod.POST, "/api/admission", body, req, ADMISSION_PROXY_TIMEOUT);
    }

    @PostMapping("/api/admission/refine")
    public ResponseEntity<byte[]> admissionRefine(@RequestBody(required = false) byte[] body, HttpServletRequest req) {
        return forwardJson(HttpMethod.POST, "/api/admission/refine", body, req, ADMISSION_PROXY_TIMEOUT);
    }

    @PostMapping("/api/admission/student-chat")
    public ResponseEntity<byte[]> studentChat(@RequestBody(required = false) byte[] body, HttpServletRequest req) {
        return forwardJson(HttpMethod.POST, "/api/admission/student-chat", body, req, ADMISSION_PROXY_TIMEOUT);
    }

    private ResponseEntity<byte[]> forwardJson(
            HttpMethod method, String path, byte[] body, HttpServletRequest req, Duration timeout) {
        WebClient.RequestBodySpec spec = aiWebClient.method(method).uri(path).headers(copyAuthHeaders(req));
        if (body != null && body.length > 0) {
            spec.contentType(MediaType.APPLICATION_JSON).bodyValue(body);
        }
        Mono<ResponseEntity<byte[]>> response = spec.exchangeToMono(resp -> resp.toEntity(byte[].class));
        if (timeout != null) {
            response = response.timeout(timeout);
        }
        try {
            return response.block();
        } catch (Exception e) {
            boolean isTimeout = e instanceof TimeoutException;
            log.warn("代理转发 {} {}：{}", path, isTimeout ? "超时" : "失败", e.getMessage());
            String message = isTimeout ? "匹配超时，请稍后重试" : "AI 服务暂时不可用，请稍后重试";
            byte[] payload = String.format(
                    "{\"error\":true,\"message\":\"%s\",\"status_code\":504}", message)
                    .getBytes(StandardCharsets.UTF_8);
            return ResponseEntity.status(504).contentType(MediaType.APPLICATION_JSON).body(payload);
        }
    }

    private Consumer<HttpHeaders> copyAuthHeaders(HttpServletRequest req) {
        String auth = req.getHeader(HttpHeaders.AUTHORIZATION);
        return headers -> {
            if (StringUtils.hasText(auth)) {
                headers.set(HttpHeaders.AUTHORIZATION, auth);
            }
        };
    }
}
