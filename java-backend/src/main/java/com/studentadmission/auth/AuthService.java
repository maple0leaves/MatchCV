package com.studentadmission.auth;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.studentadmission.auth.dto.UserResponse;
import com.studentadmission.auth.entity.User;
import com.studentadmission.auth.mapper.UserMapper;
import com.studentadmission.student.StudentService;
import com.studentadmission.common.ApiException;
import com.studentadmission.security.JwtService;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final LoginRateLimiter rateLimiter;
    private final CaptchaService captchaService;
    private final StudentService studentService;

    public AuthService(UserMapper userMapper,
                       PasswordEncoder passwordEncoder,
                       JwtService jwtService,
                       LoginRateLimiter rateLimiter,
                       CaptchaService captchaService,
                       StudentService studentService) {
        this.userMapper = userMapper;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.rateLimiter = rateLimiter;
        this.captchaService = captchaService;
        this.studentService = studentService;
    }

    private static final String DEFAULT_ROLE = "supervisor";


    public record LoginResult(String token, UserResponse user) {
    }

    public LoginResult login(String username, String password) {
        if (rateLimiter.isBlocked(username)) {
            throw new ApiException(429, "登录失败次数过多，请稍后再试");
        }

        User user = findByUsername(username);
        if (user == null || !passwordEncoder.matches(password, user.getHashedPassword())) {
            rateLimiter.recordFailure(username);
            throw ApiException.unauthorized("用户名或密码错误");
        }

        rateLimiter.reset(username);
        return issueTokens(user);
    }


    @Transactional
    public LoginResult register(
            String username,
            String password,
            String nickname,
            String captchaId,
            String captchaCode) {
        captchaService.validate(captchaId, captchaCode);
        if (findByUsername(username) != null) {
            throw ApiException.badRequest("该用户名已被注册，换一个或直接登录");
        }

        User user = new User();
        user.setUsername(username);
        user.setNickname(hasText(nickname) ? nickname : username);
        user.setHashedPassword(passwordEncoder.encode(password));
        user.setRole(DEFAULT_ROLE);
        userMapper.insert(user);

        studentService.seedDefaultResumes(user.getId());
        return issueTokens(user);
    }

    private LoginResult issueTokens(User user) {
        String userId = String.valueOf(user.getId());
        String token = jwtService.createToken(userId, user.getRole());
        String nickname = hasText(user.getNickname()) ? user.getNickname() : user.getUsername();
        UserResponse userResponse = new UserResponse(user.getId(), user.getUsername(), nickname, user.getRole());
        return new LoginResult(token, userResponse);
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    public void changePassword(String userId, String oldPassword, String newPassword) {
        User user = userMapper.selectById(Long.valueOf(userId));
        if (user == null) {
            throw ApiException.notFound("用户不存在");
        }
        if (!passwordEncoder.matches(oldPassword, user.getHashedPassword())) {
            throw ApiException.badRequest("原密码错误");
        }
        user.setHashedPassword(passwordEncoder.encode(newPassword));
        userMapper.updateById(user);
    }

    private User findByUsername(String username) {
        return userMapper.selectOne(
                Wrappers.<User>lambdaQuery().eq(User::getUsername, username));
    }
}
