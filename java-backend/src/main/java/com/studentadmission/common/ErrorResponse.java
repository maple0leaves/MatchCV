package com.studentadmission.common;





public record ErrorResponse(boolean error, String message, int status_code) {

    public static ErrorResponse of(int statusCode, String message) {
        return new ErrorResponse(true, message, statusCode);
    }
}
