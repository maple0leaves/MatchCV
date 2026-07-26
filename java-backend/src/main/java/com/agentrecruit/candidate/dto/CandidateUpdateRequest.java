package com.agentrecruit.candidate.dto;

/** 可编辑字段，null 表示不更新（对应 Python CandidateUpdate exclude_none）。 */
public record CandidateUpdateRequest(
        String name,
        String email,
        String phone,
        String skills,
        String education,
        String experience) {
}
