package com.studentadmission.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;


@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class ProductionConfigValidator implements ApplicationRunner {

    private final String environment;
    private final String jwtSecret;
    private final String internalToken;
    private final String adminPassword;
    private final String mysqlPassword;
    private final String corsOrigins;
    private final String resumeDir;

    public ProductionConfigValidator(
            @Value("${app.environment}") String environment,
            @Value("${app.jwt.secret}") String jwtSecret,
            @Value("${app.ai.internal-token}") String internalToken,
            @Value("${app.admin.password}") String adminPassword,
            @Value("${spring.datasource.password}") String mysqlPassword,
            @Value("${app.cors.origins}") String corsOrigins,
            @Value("${app.resume.dir}") String resumeDir) {
        this.environment = environment;
        this.jwtSecret = jwtSecret;
        this.internalToken = internalToken;
        this.adminPassword = adminPassword;
        this.mysqlPassword = mysqlPassword;
        this.corsOrigins = corsOrigins;
        this.resumeDir = resumeDir;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (!"production".equalsIgnoreCase(environment)) {
            return;
        }
        List<String> errors = new ArrayList<>();
        requireSecret(errors, "JWT_SECRET", jwtSecret,
                "change-me-in-production-use-random-32-bytes", 32);
        requireSecret(errors, "INTERNAL_SERVICE_TOKEN", internalToken,
                "dev-internal-token-change-in-production", 32);
        requireSecret(errors, "ADMIN_PASSWORD", adminPassword, "admin123", 12);
        requireSecret(errors, "MYSQL_PASSWORD", mysqlPassword, "hellojobs123", 16);
        String cors = corsOrigins.toLowerCase(Locale.ROOT);
        if (cors.contains("localhost") || cors.contains("127.0.0.1") || cors.contains("*")) {
            errors.add("CORS_ORIGINS 不能包含 localhost、127.0.0.1 或通配符");
        }
        if (resumeDir.contains("change-me")) {
            errors.add("RESUME_DIR 仍是占位路径");
        }
        if (!errors.isEmpty()) {
            throw new IllegalStateException(
                    "生产配置校验失败：\n- " + String.join("\n- ", errors));
        }
    }

    private static void requireSecret(List<String> errors, String name, String value,
                                      String forbidden, int minLength) {
        if (value == null || value.isBlank() || value.equals(forbidden)
                || value.length() < minLength) {
            errors.add(name + " 未设置、仍为默认值或长度不足 " + minLength + " 位");
        }
    }
}
