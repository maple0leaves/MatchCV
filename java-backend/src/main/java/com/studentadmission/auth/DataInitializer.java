package com.studentadmission.auth;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.studentadmission.auth.entity.User;
import com.studentadmission.auth.mapper.UserMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;


@Slf4j
@Component
public class DataInitializer implements CommandLineRunner {

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final String adminUsername;
    private final String adminPassword;

    public DataInitializer(UserMapper userMapper,
                           PasswordEncoder passwordEncoder,
                           @Value("${app.admin.username}") String adminUsername,
                           @Value("${app.admin.password}") String adminPassword) {
        this.userMapper = userMapper;
        this.passwordEncoder = passwordEncoder;
        this.adminUsername = adminUsername;
        this.adminPassword = adminPassword;
    }

    @Override
    public void run(String... args) {
        Long count = userMapper.selectCount(
                Wrappers.<User>lambdaQuery().eq(User::getUsername, adminUsername));
        if (count != null && count > 0) {
            log.info("管理员用户 '{}' 已存在，跳过创建。", adminUsername);
            return;
        }
        User admin = new User();
        admin.setUsername(adminUsername);
        admin.setNickname(adminUsername);
        admin.setHashedPassword(passwordEncoder.encode(adminPassword));
        admin.setRole("admin");
        userMapper.insert(admin);
        log.info("管理员用户 '{}' 创建成功。", adminUsername);
    }
}
