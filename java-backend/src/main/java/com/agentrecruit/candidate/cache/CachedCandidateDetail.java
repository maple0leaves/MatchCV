package com.agentrecruit.candidate.cache;

import com.agentrecruit.candidate.dto.CandidateResponse;

public record CachedCandidateDetail(
        int schemaVersion,
        boolean found,
        CandidateResponse candidate) {

    public static final int CURRENT_SCHEMA_VERSION = 1;

    public static CachedCandidateDetail found(CandidateResponse candidate) {
        return new CachedCandidateDetail(CURRENT_SCHEMA_VERSION, true, candidate);
    }

    public static CachedCandidateDetail notFound() {
        return new CachedCandidateDetail(CURRENT_SCHEMA_VERSION, false, null);
    }
}
