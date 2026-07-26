package com.agentrecruit.candidate.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.agentrecruit.candidate.entity.Candidate;

import java.time.LocalDateTime;

public record CandidateResponse(
        Long id,
        String name,
        String email,
        String phone,
        String skills,
        String education,
        String experience,
        String status,
        String resume_file_path,
        String status_note,
        String parse_status,
        @JsonFormat(shape = JsonFormat.Shape.STRING) LocalDateTime parsed_at,
        @JsonFormat(shape = JsonFormat.Shape.STRING) LocalDateTime created_at,
        @JsonFormat(shape = JsonFormat.Shape.STRING) LocalDateTime updated_at) {

    public static CandidateResponse from(Candidate c) {
        return new CandidateResponse(
                c.getId(), c.getName(), c.getEmail(), c.getPhone(), c.getSkills(),
                c.getEducation(), c.getExperience() == null ? "" : c.getExperience(),
                c.getStatus(), c.getResumeFilePath(), c.getStatusNote(),
                hasText(c.getParseStatus()) ? c.getParseStatus() : parseStatus(c),
                c.getParsedAt(), c.getCreatedAt(), c.getUpdatedAt());
    }

    private static String parseStatus(Candidate c) {
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
