package com.agentrecruit.security;

/** Authenticated principal extracted from the JWT. */
public record AuthUser(String userId, String role) {
}
