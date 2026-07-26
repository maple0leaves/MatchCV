package com.agentrecruit.common;

/**
 * Unified API error body, identical to the existing FastAPI shape:
 * {"error": true, "message": "...", "status_code": 4xx}
 */
public record ErrorResponse(boolean error, String message, int status_code) {

    public static ErrorResponse of(int statusCode, String message) {
        return new ErrorResponse(true, message, statusCode);
    }
}
