package com.studentadmission;

import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class StudentAdmissionApplicationTest {

    @Test
    void excludesDefaultGeneratedUserAutoConfiguration() {
        SpringBootApplication annotation =
                StudentAdmissionApplication.class.getAnnotation(SpringBootApplication.class);

        assertNotNull(annotation);
        assertTrue(Arrays.asList(annotation.exclude())
                .contains(UserDetailsServiceAutoConfiguration.class));
    }
}
