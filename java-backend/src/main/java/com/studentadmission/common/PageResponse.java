package com.studentadmission.common;

import java.util.List;


public record PageResponse<T>(List<T> items, long total, long page, long page_size) {
}
