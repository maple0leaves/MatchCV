package com.agentrecruit.config;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ProductionConfigValidatorTest {

    @Test
    void rejectsDevelopmentSecretsInProduction() {
        ProductionConfigValidator validator = new ProductionConfigValidator(
                "production",
                "change-me-in-production-use-random-32-bytes",
                "dev-internal-token-change-in-production",
                "admin123",
                "hellojobs123",
                "http://localhost:5173",
                "/app/data/resumes");

        assertThrows(IllegalStateException.class, () -> validator.run(null));
    }

    @Test
    void acceptsStrongProductionConfiguration() {
        ProductionConfigValidator validator = new ProductionConfigValidator(
                "production",
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "admin-validation-password-2026",
                "mysql-validation-password-2026",
                "https://validation.example.com",
                "/app/data/resumes");

        assertDoesNotThrow(() -> validator.run(null));
    }
}
