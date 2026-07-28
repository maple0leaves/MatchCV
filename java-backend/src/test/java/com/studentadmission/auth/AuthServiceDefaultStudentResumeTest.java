package com.studentadmission.auth;

import com.studentadmission.auth.entity.User;
import com.studentadmission.auth.mapper.UserMapper;
import com.studentadmission.student.StudentService;
import com.studentadmission.security.JwtService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.crypto.password.PasswordEncoder;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthServiceDefaultStudentResumeTest {

    @Test
    void registrationSeedsDefaultResumesForCreatedUser() {
        UserMapper userMapper = mock(UserMapper.class);
        PasswordEncoder passwordEncoder = mock(PasswordEncoder.class);
        JwtService jwtService = mock(JwtService.class);
        LoginRateLimiter rateLimiter = mock(LoginRateLimiter.class);
        CaptchaService captchaService = mock(CaptchaService.class);
        StudentService studentService = mock(StudentService.class);
        AuthService service = new AuthService(
                userMapper,
                passwordEncoder,
                jwtService,
                rateLimiter,
                captchaService,
                studentService);

        when(userMapper.selectOne(any())).thenReturn(null);
        when(passwordEncoder.encode("12345678")).thenReturn("hashed-password");
        doAnswer(invocation -> {
            User user = invocation.getArgument(0);
            user.setId(42L);
            return 1;
        }).when(userMapper).insert(any(User.class));
        when(jwtService.createToken("42", "supervisor")).thenReturn("token");

        AuthService.LoginResult result = service.register(
                "new-user",
                "12345678",
                "",
                "captcha-id",
                "A7K9");

        ArgumentCaptor<User> userCaptor = ArgumentCaptor.forClass(User.class);
        verify(userMapper).insert(userCaptor.capture());
        assertThat(userCaptor.getValue().getNickname()).isEqualTo("new-user");
        verify(captchaService).validate("captcha-id", "A7K9");
        verify(studentService).seedDefaultResumes(42L);
        assertThat(result.token()).isEqualTo("token");
        assertThat(result.user().id()).isEqualTo(42L);
    }
}
