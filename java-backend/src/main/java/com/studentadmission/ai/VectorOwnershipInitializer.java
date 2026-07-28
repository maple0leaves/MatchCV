package com.studentadmission.ai;

import com.studentadmission.student.entity.Student;
import com.studentadmission.student.mapper.StudentMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;





@Slf4j
@Order(100)
@Component
public class VectorOwnershipInitializer implements ApplicationRunner {

    private final StudentMapper studentMapper;
    private final AiClient aiClient;

    public VectorOwnershipInitializer(StudentMapper studentMapper, AiClient aiClient) {
        this.studentMapper = studentMapper;
        this.aiClient = aiClient;
    }

    @Override
    public void run(ApplicationArguments args) {
        List<Map<String, Object>> mappings = studentMapper.selectList(null).stream()
                .filter(student -> student.getOwnerUserId() != null)
                .filter(student -> StringUtils.hasText(student.getResumeFilePath()))
                .map(this::toMapping)
                .toList();
        if (!mappings.isEmpty() && !aiClient.syncVectorOwnership(mappings)) {
            log.warn("历史学生向量归属尚未同步；旧数据需重新解析后才能参与智能匹配");
        }
    }

    private Map<String, Object> toMapping(Student student) {
        Map<String, Object> mapping = new LinkedHashMap<>();
        mapping.put("owner_user_id", student.getOwnerUserId());
        mapping.put("source", student.getResumeFilePath());
        return mapping;
    }
}
