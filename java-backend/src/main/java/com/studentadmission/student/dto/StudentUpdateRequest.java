package com.studentadmission.student.dto;


public record StudentUpdateRequest(
        String name,
        String email,
        String phone,
        String skills,
        String education,
        String research_experience) {
}
