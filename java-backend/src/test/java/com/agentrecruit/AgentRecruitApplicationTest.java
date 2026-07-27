package com.agentrecruit;

import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AgentRecruitApplicationTest {

    @Test
    void excludesDefaultGeneratedUserAutoConfiguration() {
        SpringBootApplication annotation =
                AgentRecruitApplication.class.getAnnotation(SpringBootApplication.class);

        assertNotNull(annotation);
        assertTrue(Arrays.asList(annotation.exclude())
                .contains(UserDetailsServiceAutoConfiguration.class));
    }
}
