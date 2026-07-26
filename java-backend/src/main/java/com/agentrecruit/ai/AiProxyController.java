package com.agentrecruit.ai;

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

/**
 * AI 网关：把 /api/recruit 反向代理到 Python AI 服务。
 * 透传 Authorization 头，使 Python 端鉴权（共享 JWT 密钥）继续生效。
 * 对前端而言 Python 完全透明。
 */
@Slf4j
@RestController
public class AiProxyController {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * 比 Python 侧 /api/recruit(/refine) 自己的总超时（RECRUIT_REQUEST_TIMEOUT_SECONDS，
     * 默认 90s）多留 10 秒缓冲：让 Python 自己的超时错误优先返回（带明确的"匹配超时，
     * 请稍后重试"提示），而不是 Java 先把连接掐断、前端只看到一个笼统的网络错误。
     */
    private static final Duration RECRUIT_PROXY_TIMEOUT = Duration.ofSeconds(100);

    private final WebClient aiWebClient;

    public AiProxyController(WebClient aiWebClient) {
        this.aiWebClient = aiWebClient;
    }

    @PostMapping("/api/recruit")
    public ResponseEntity<byte[]> recruit(@RequestBody(required = false) byte[] body, HttpServletRequest req) {
        return forwardJson(HttpMethod.POST, "/api/recruit", body, req, RECRUIT_PROXY_TIMEOUT);
    }

    @PostMapping("/api/recruit/refine")
    public ResponseEntity<byte[]> recruitRefine(@RequestBody(required = false) byte[] body, HttpServletRequest req) {
        return forwardJson(HttpMethod.POST, "/api/recruit/refine", body, req, RECRUIT_PROXY_TIMEOUT);
    }

    @PostMapping("/api/recruit/candidate-chat")
    public ResponseEntity<byte[]> candidateChat(@RequestBody(required = false) byte[] body, HttpServletRequest req) {
        return forwardJson(HttpMethod.POST, "/api/recruit/candidate-chat", body, req, RECRUIT_PROXY_TIMEOUT);
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
