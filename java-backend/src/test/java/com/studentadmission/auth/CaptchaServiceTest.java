package com.studentadmission.auth;

import com.studentadmission.auth.dto.CaptchaResponse;
import com.studentadmission.common.ApiException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class CaptchaServiceTest {

    private StringRedisTemplate redis;
    private ValueOperations<String, String> values;
    private CaptchaService service;

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        service = new CaptchaService(redis, 180);
    }

    @Test
    void createStoresFourCharacterCodeAndReturnsSvgDataUri() {
        CaptchaResponse response = service.create();

        ArgumentCaptor<String> codeCaptor = ArgumentCaptor.forClass(String.class);
        verify(values).set(
                eq("captcha:register:" + response.captcha_id()),
                codeCaptor.capture(),
                eq(Duration.ofSeconds(180)));
        assertThat(codeCaptor.getValue()).matches("[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}");
        assertThat(response.image()).startsWith("data:image/svg+xml;base64,");
        assertThat(response.expires_in_seconds()).isEqualTo(180);
    }

    @Test
    void validateAcceptsCaseInsensitiveCodeAndConsumesIt() {
        when(values.getAndDelete("captcha:register:captcha-id")).thenReturn("A7K9");

        assertDoesNotThrow(() -> service.validate("captcha-id", " a7k9 "));

        verify(values).getAndDelete("captcha:register:captcha-id");
    }

    @Test
    void validateRejectsExpiredCaptcha() {
        when(values.getAndDelete("captcha:register:expired-id")).thenReturn(null);

        ApiException error = assertThrows(
                ApiException.class,
                () -> service.validate("expired-id", "A7K9"));

        assertThat(error.getStatusCode()).isEqualTo(400);
        assertThat(error.getMessage()).contains("已过期");
    }

    @Test
    void validateRejectsWrongCodeAfterConsumingCaptcha() {
        when(values.getAndDelete("captcha:register:captcha-id")).thenReturn("A7K9");

        ApiException error = assertThrows(
                ApiException.class,
                () -> service.validate("captcha-id", "B8M2"));

        assertThat(error.getStatusCode()).isEqualTo(400);
        assertThat(error.getMessage()).contains("验证码错误");
        verify(values).getAndDelete("captcha:register:captcha-id");
    }

    @Test
    void validateRejectsMissingInputWithoutReadingRedis() {
        ApiException error = assertThrows(
                ApiException.class,
                () -> service.validate("", ""));

        assertThat(error.getStatusCode()).isEqualTo(400);
        assertThat(error.getMessage()).contains("图形验证码");
        verifyNoInteractions(values);
    }
}
