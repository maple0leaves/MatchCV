package com.agentrecruit.messaging;

public class PermanentResumeParseException extends RuntimeException {

    public PermanentResumeParseException(String message, Throwable cause) {
        super(message, cause);
    }

    public PermanentResumeParseException(String message) {
        super(message);
    }
}
