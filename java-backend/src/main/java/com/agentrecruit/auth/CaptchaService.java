package com.agentrecruit.auth;

import com.agentrecruit.auth.dto.CaptchaResponse;
import com.agentrecruit.common.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.Base64;
import java.util.Locale;
import java.util.UUID;

@Service
public class CaptchaService {

    private static final String REDIS_PREFIX = "captcha:register:";
    private static final String ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
    private static final int CODE_LENGTH = 4;
    private static final int IMAGE_WIDTH = 132;
    private static final int IMAGE_HEIGHT = 46;

    private final StringRedisTemplate redis;
    private final int expiresSeconds;
    private final SecureRandom random = new SecureRandom();

    public CaptchaService(
            StringRedisTemplate redis,
            @Value("${app.captcha.expires-seconds:180}") int expiresSeconds) {
        this.redis = redis;
        this.expiresSeconds = Math.max(30, expiresSeconds);
    }

    public CaptchaResponse create() {
        String captchaId = UUID.randomUUID().toString();
        String code = randomCode();
        redis.opsForValue().set(
                REDIS_PREFIX + captchaId,
                code,
                Duration.ofSeconds(expiresSeconds));
        return new CaptchaResponse(captchaId, createSvgDataUri(code), expiresSeconds);
    }

    public void validate(String captchaId, String captchaCode) {
        if (captchaId == null || captchaId.isBlank() || captchaCode == null || captchaCode.isBlank()) {
            throw ApiException.badRequest("请输入图形验证码");
        }

        String expected = redis.opsForValue().getAndDelete(REDIS_PREFIX + captchaId);
        if (expected == null) {
            throw ApiException.badRequest("验证码已过期，请刷新后重试");
        }

        String actual = captchaCode.trim().toUpperCase(Locale.ROOT);
        if (!expected.equals(actual)) {
            throw ApiException.badRequest("验证码错误，请重新输入");
        }
    }

    private String randomCode() {
        StringBuilder code = new StringBuilder(CODE_LENGTH);
        for (int index = 0; index < CODE_LENGTH; index++) {
            code.append(ALPHABET.charAt(random.nextInt(ALPHABET.length())));
        }
        return code.toString();
    }

    private String createSvgDataUri(String code) {
        StringBuilder svg = new StringBuilder(900);
        svg.append("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"")
                .append(IMAGE_WIDTH)
                .append("\" height=\"")
                .append(IMAGE_HEIGHT)
                .append("\" viewBox=\"0 0 ")
                .append(IMAGE_WIDTH)
                .append(' ')
                .append(IMAGE_HEIGHT)
                .append("\">")
                .append("<rect width=\"100%\" height=\"100%\" rx=\"7\" fill=\"#eaf7fb\"/>");

        for (int index = 0; index < 5; index++) {
            int y1 = 6 + random.nextInt(34);
            int y2 = 6 + random.nextInt(34);
            String color = index % 2 == 0 ? "#45a9c9" : "#8ac7d7";
            svg.append("<path d=\"M0 ")
                    .append(y1)
                    .append(" L132 ")
                    .append(y2)
                    .append("\" stroke=\"")
                    .append(color)
                    .append("\" stroke-width=\"1\" opacity=\".55\"/>");
        }

        for (int index = 0; index < 12; index++) {
            svg.append("<circle cx=\"")
                    .append(4 + random.nextInt(124))
                    .append("\" cy=\"")
                    .append(4 + random.nextInt(38))
                    .append("\" r=\"")
                    .append(1 + random.nextInt(2))
                    .append("\" fill=\"#5a9fb5\" opacity=\".45\"/>");
        }

        for (int index = 0; index < code.length(); index++) {
            int x = 16 + index * 28 + random.nextInt(5);
            int y = 31 + random.nextInt(7);
            int angle = random.nextInt(25) - 12;
            svg.append("<text x=\"")
                    .append(x)
                    .append("\" y=\"")
                    .append(y)
                    .append("\" transform=\"rotate(")
                    .append(angle)
                    .append(' ')
                    .append(x)
                    .append(' ')
                    .append(y)
                    .append(")\" font-family=\"monospace\" font-size=\"25\" font-weight=\"700\" fill=\"#173c4a\">")
                    .append(code.charAt(index))
                    .append("</text>");
        }

        svg.append("</svg>");
        String encoded = Base64.getEncoder().encodeToString(svg.toString().getBytes(StandardCharsets.UTF_8));
        return "data:image/svg+xml;base64," + encoded;
    }
}
