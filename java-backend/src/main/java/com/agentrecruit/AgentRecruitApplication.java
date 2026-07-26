package com.agentrecruit;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
@MapperScan("com.agentrecruit.**.mapper")
public class AgentRecruitApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentRecruitApplication.class, args);
    }
}
