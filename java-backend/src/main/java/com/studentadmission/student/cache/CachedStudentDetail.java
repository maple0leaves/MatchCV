package com.studentadmission.student.cache;

import com.studentadmission.student.dto.StudentResponse;

public record CachedStudentDetail(
        int schemaVersion,
        boolean found,
        StudentResponse student) {

    public static final int CURRENT_SCHEMA_VERSION = 1;

    public static CachedStudentDetail found(StudentResponse student) {
        return new CachedStudentDetail(CURRENT_SCHEMA_VERSION, true, student);
    }

    public static CachedStudentDetail notFound() {
        return new CachedStudentDetail(CURRENT_SCHEMA_VERSION, false, null);
    }
}
