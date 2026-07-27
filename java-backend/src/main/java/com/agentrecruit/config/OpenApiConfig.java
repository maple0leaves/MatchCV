package com.agentrecruit.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI helloJobsOpenAPI() {
        return new OpenAPI().info(new Info()
                .title("AgentRecruit 业务后端 API")
                .description("Java 业务后端（与 Python AI 服务共存）")
                .version("1.0.0"));
    }
}
