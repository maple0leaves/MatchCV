package com.agentrecruit.auth;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.agentrecruit.auth.dto.UserResponse;
import com.agentrecruit.auth.entity.User;
import com.agentrecruit.auth.mapper.UserMapper;
import com.agentrecruit.candidate.CandidateService;
import com.agentrecruit.common.ApiException;
import com.agentrecruit.security.JwtService;
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
    private final CandidateService candidateService;

    public AuthService(UserMapper userMapper,
                       PasswordEncoder passwordEncoder,
                       JwtService jwtService,
                       LoginRateLimiter rateLimiter,
                       CaptchaService captchaService,
                       CandidateService candidateService) {
        this.userMapper = userMapper;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.rateLimiter = rateLimiter;
        this.captchaService = captchaService;
        this.candidateService = candidateService;
    }

    private static final String DEFAULT_ROLE = "recruiter";

    /** 登录结果：携带 token 与用户信息。 */
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

    /** 注册新用户（默认角色 recruiter），成功后直接返回登录态，前端无需再次登录。 */
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

        candidateService.seedDefaultResumes(user.getId());
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
