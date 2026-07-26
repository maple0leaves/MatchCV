package com.agentrecruit.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

@Configuration
public class WebClientConfig {

    @Bean
    public WebClient aiWebClient(@Value("${app.ai.base-url}") String aiBaseUrl,
                                 @Value("${app.ai.internal-token}") String internalToken) {
        return WebClient.builder()
                .baseUrl(aiBaseUrl)
                .defaultHeader("X-Internal-Token", internalToken)
                // SSE/大响应不限制缓冲（16MB）
                .codecs(c -> c.defaultCodecs().maxInMemorySize(16 * 1024 * 1024))
                .build();
    }
}
