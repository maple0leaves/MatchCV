package com.studentadmission.auth;

import com.studentadmission.auth.dto.ChangePasswordRequest;
import com.studentadmission.auth.dto.CaptchaResponse;
import com.studentadmission.auth.dto.LoginRequest;
import com.studentadmission.auth.dto.LoginResponse;
import com.studentadmission.auth.dto.RegisterRequest;
import com.studentadmission.common.ApiException;
import com.studentadmission.security.AuthUser;
import com.studentadmission.security.JwtBlacklist;
import com.studentadmission.security.JwtService;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;
    private final JwtService jwtService;
    private final JwtBlacklist blacklist;
    private final CaptchaService captchaService;

    public AuthController(
            AuthService authService,
            JwtService jwtService,
            JwtBlacklist blacklist,
            CaptchaService captchaService) {
        this.authService = authService;
        this.jwtService = jwtService;
        this.blacklist = blacklist;
        this.captchaService = captchaService;
    }

    @GetMapping("/captcha")
    public ResponseEntity<CaptchaResponse> captcha() {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(captchaService.create());
    }

    @PostMapping("/login")
    public LoginResponse login(@Valid @RequestBody LoginRequest request) {
        AuthService.LoginResult result = authService.login(request.username(), request.password());
        return LoginResponse.of(result.token(), result.user());
    }

    @PostMapping("/register")
    public LoginResponse register(@Valid @RequestBody RegisterRequest request) {
        AuthService.LoginResult result = authService.register(
                request.username(),
                request.password(),
                request.nickname(),
                request.captcha_id(),
                request.captcha_code());
        return LoginResponse.of(result.token(), result.user());
    }

    @PostMapping("/logout")
    public Map<String, String> logout(HttpServletRequest request) {
        String token = resolveToken(request);
        if (token != null) {
            try {
                Claims claims = jwtService.parse(token);
                long ttl = (claims.getExpiration().getTime() - System.currentTimeMillis()) / 1000;
                blacklist.revoke(token, ttl);
            } catch (Exception ignored) {

            }
        }
        return Map.of("message", "已登出");
    }

    @GetMapping("/me")
    public Map<String, String> me() {
        AuthUser user = currentUser();
        Map<String, String> body = new LinkedHashMap<>();
        body.put("sub", user.userId());
        body.put("role", user.role());
        return body;
    }

    @PatchMapping("/password")
    public Map<String, String> changePassword(@Valid @RequestBody ChangePasswordRequest request) {
        AuthUser user = currentUser();
        authService.changePassword(user.userId(), request.old_password(), request.new_password());
        return Map.of("message", "密码修改成功");
    }

    private AuthUser currentUser() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !(auth.getPrincipal() instanceof AuthUser authUser)) {
            throw ApiException.unauthorized("未登录或登录已过期");
        }
        return authUser;
    }

    private String resolveToken(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")) {
            return header.substring(7).trim();
        }
        return null;
    }
}
