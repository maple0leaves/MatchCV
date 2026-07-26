package com.agentrecruit.common;

import java.util.List;

/** 统一分页响应，与 FastAPI 的 {items,total,page,page_size} 一致。 */
public record PageResponse<T>(List<T> items, long total, long page, long page_size) {
}
