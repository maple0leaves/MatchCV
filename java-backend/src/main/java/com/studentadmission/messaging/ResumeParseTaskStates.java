package com.studentadmission.messaging;

public final class ResumeParseTaskStates {

    public static final String PENDING = "PENDING";
    public static final String PROCESSING = "PROCESSING";
    public static final String SUCCESS = "SUCCESS";
    public static final String FAILED = "FAILED";
    public static final String DEAD = "DEAD";
    public static final String CANCELLED = "CANCELLED";

    public static final String MQ_PENDING = "PENDING";
    public static final String MQ_SENT = "SENT";

    private ResumeParseTaskStates() {
    }
}
