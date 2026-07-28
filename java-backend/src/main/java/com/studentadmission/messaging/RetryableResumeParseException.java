package com.studentadmission.messaging;

public class RetryableResumeParseException extends RuntimeException {

    public RetryableResumeParseException(String message, Throwable cause) {
        super(message, cause);
    }

    public RetryableResumeParseException(String message) {
        super(message);
    }
}
