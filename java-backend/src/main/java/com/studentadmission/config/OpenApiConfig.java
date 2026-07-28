package com.studentadmission.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI studentAdmissionOpenAPI() {
        return new OpenAPI().info(new Info()
                .title("MatchCV 学生招生筛选 API")
                .description("导师筛选硕士申请学生的 Java 业务后端")
                .version("1.0.0"));
    }
}
