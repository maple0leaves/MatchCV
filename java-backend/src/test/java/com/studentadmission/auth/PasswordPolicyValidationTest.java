package com.studentadmission.auth;

import com.studentadmission.auth.dto.ChangePasswordRequest;
import com.studentadmission.auth.dto.RegisterRequest;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PasswordPolicyValidationTest {

    private final Validator validator = Validation.buildDefaultValidatorFactory().getValidator();

    @Test
    void registrationPasswordMustBeBetweenEightAndThirtyTwoCharacters() {
        RegisterRequest tooShort = registerRequest("1234567");
        RegisterRequest minimum = registerRequest("12345678");
        RegisterRequest maximum = registerRequest("a".repeat(32));
        RegisterRequest tooLong = registerRequest("a".repeat(33));

        assertThat(validator.validate(tooShort))
                .extracting(violation -> violation.getMessage())
                .contains("密码长度需为 8-32 位");
        assertThat(validator.validate(minimum)).isEmpty();
        assertThat(validator.validate(maximum)).isEmpty();
        assertThat(validator.validate(tooLong))
                .extracting(violation -> violation.getMessage())
                .contains("密码长度需为 8-32 位");
    }

    @Test
    void changedPasswordUsesTheSameLengthPolicy() {
        assertThat(validator.validate(new ChangePasswordRequest("old-password", "1234567")))
                .extracting(violation -> violation.getMessage())
                .contains("新密码长度需为 8-32 位");
        assertThat(validator.validate(new ChangePasswordRequest("old-password", "12345678"))).isEmpty();
        assertThat(validator.validate(new ChangePasswordRequest("old-password", "a".repeat(32)))).isEmpty();
        assertThat(validator.validate(new ChangePasswordRequest("old-password", "a".repeat(33))))
                .extracting(violation -> violation.getMessage())
                .contains("新密码长度需为 8-32 位");
    }

    private RegisterRequest registerRequest(String password) {
        return new RegisterRequest("student", password, "学生", "captcha-id", "A7K9");
    }
}
