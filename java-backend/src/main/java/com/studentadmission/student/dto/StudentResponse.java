package com.studentadmission.student.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.studentadmission.student.entity.Student;

import java.time.LocalDateTime;

public record StudentResponse(
        Long id,
        String name,
        String email,
        String phone,
        String skills,
        String education,
        String research_experience,
        String status,
        String resume_file_path,
        String status_note,
        String parse_status,
        @JsonFormat(shape = JsonFormat.Shape.STRING) LocalDateTime parsed_at,
        @JsonFormat(shape = JsonFormat.Shape.STRING) LocalDateTime created_at,
        @JsonFormat(shape = JsonFormat.Shape.STRING) LocalDateTime updated_at) {

    public static StudentResponse from(Student c) {
        return new StudentResponse(
                c.getId(), c.getName(), c.getEmail(), c.getPhone(), c.getSkills(),
                c.getEducation(), c.getResearchExperience() == null ? "" : c.getResearchExperience(),
                c.getStatus(), c.getResumeFilePath(), c.getStatusNote(),
                hasText(c.getParseStatus()) ? c.getParseStatus() : parseStatus(c),
                c.getParsedAt(), c.getCreatedAt(), c.getUpdatedAt());
    }

    private static String parseStatus(Student c) {
        if (c.getParsedAt() != null) {
            return "parsed";
        }

        String note = c.getStatusNote() == null ? "" : c.getStatusNote();
        if (note.contains("失败") || note.contains("未能") || note.contains("无法")) {
            return "failed";
        }

        if (hasText(c.getResumeFilePath()) && !hasText(c.getSkills())) {
            return "parsing";
        }

        return "pending";
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }
}
