package com.agentrecruit.candidate;

import com.agentrecruit.candidate.dto.CandidateResponse;
import com.agentrecruit.candidate.dto.CandidateStatusUpdateRequest;
import com.agentrecruit.candidate.dto.CandidateUpdateRequest;
import com.agentrecruit.common.PageResponse;
import com.agentrecruit.security.AuthUser;
import jakarta.validation.Valid;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/candidates")
public class CandidateController {

    private final CandidateService candidateService;

    public CandidateController(CandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @PostMapping("/upload")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> upload(@AuthenticationPrincipal AuthUser user,
                                      @RequestParam("file") MultipartFile file) {
        CandidateService.UploadResult result = candidateService.upload(currentUserId(user), file);
        Map<String, Object> body = toUploadMap(result);
        return body;
    }

    @PostMapping("/upload/batch")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> uploadBatch(@AuthenticationPrincipal AuthUser user,
                                           @RequestParam("files") List<MultipartFile> files) {
        CandidateService.BatchUploadResult result = candidateService.uploadBatch(currentUserId(user), files);
        List<Map<String, Object>> items = result.items().stream()
                .map(this::toUploadMap)
                .toList();

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("items", items);
        body.put("failures", result.failures());
        body.put("success_count", items.size());
        body.put("failure_count", result.failures().size());
        body.put("total_count", items.size() + result.failures().size());
        return body;
    }

    private Map<String, Object> toUploadMap(CandidateService.UploadResult result) {
        Map<String, Object> body = new LinkedHashMap<>(toMap(result.candidate()));
        body.put("filename", result.filename());
        if (!result.warnings().isEmpty()) {
            body.put("warnings", result.warnings());
        }
        return body;
    }

    @GetMapping
    public PageResponse<CandidateResponse> list(
            @AuthenticationPrincipal AuthUser user,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(name = "page_size", defaultValue = "20") int pageSize,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String keyword) {
        return candidateService.list(currentUserId(user), page, pageSize, status, keyword);
    }

    @GetMapping("/{id}")
    public CandidateResponse get(@AuthenticationPrincipal AuthUser user, @PathVariable Long id) {
        return candidateService.get(currentUserId(user), id);
    }

    @PutMapping("/{id}")
    public CandidateResponse update(@AuthenticationPrincipal AuthUser user,
                                    @PathVariable Long id,
                                    @RequestBody CandidateUpdateRequest request) {
        return candidateService.update(currentUserId(user), id, request);
    }

    /** 预览/下载候选人上传的原始简历文件（PDF）。 */
    @GetMapping("/{id}/resume-file")
    public ResponseEntity<byte[]> resumeFile(@AuthenticationPrincipal AuthUser user, @PathVariable Long id) {
        return toResumeFileResponse(candidateService.resumeFile(currentUserId(user), id));
    }

    /**
     * 按简历文件路径预览原始文件，供"智能匹配结果"页使用——那边只有 AI 返回的
     * resume_source 路径，没有候选人 id，所以单独开一个按路径查找的入口。
     */
    @GetMapping("/resume-file")
    public ResponseEntity<byte[]> resumeFileBySource(@AuthenticationPrincipal AuthUser user,
                                                     @RequestParam String source) {
        return toResumeFileResponse(candidateService.resumeFileBySource(currentUserId(user), source));
    }

    private ResponseEntity<byte[]> toResumeFileResponse(CandidateService.ResumeFile file) {
        String encodedName = URLEncoder.encode(file.filename(), StandardCharsets.UTF_8).replace("+", "%20");
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(file.contentType()))
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "inline; filename=\"" + file.filename() + "\"; filename*=UTF-8''" + encodedName)
                .body(file.content());
    }

    /** 异步提交一次重新解析任务，前端通过现有的候选人轮询获取最终结果。 */
    @PostMapping("/{id}/reparse")
    public CandidateResponse reparse(@AuthenticationPrincipal AuthUser user, @PathVariable Long id) {
        return candidateService.reparse(currentUserId(user), id);
    }

    @PatchMapping("/{id}/status")
    public CandidateResponse updateStatus(@AuthenticationPrincipal AuthUser user,
                                          @PathVariable Long id,
                                          @Valid @RequestBody CandidateStatusUpdateRequest request) {
        return candidateService.updateStatus(
                currentUserId(user), id, request.status(), request.status_note());
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@AuthenticationPrincipal AuthUser user, @PathVariable Long id) {
        candidateService.delete(currentUserId(user), id);
    }

    private static Long currentUserId(AuthUser user) {
        if (user == null || user.userId() == null) {
            throw new IllegalStateException("认证用户信息缺失");
        }
        return Long.valueOf(user.userId());
    }

    private Map<String, Object> toMap(CandidateResponse c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", c.id());
        m.put("name", c.name());
        m.put("email", c.email());
        m.put("phone", c.phone());
        m.put("skills", c.skills());
        m.put("education", c.education());
        m.put("experience", c.experience());
        m.put("status", c.status());
        m.put("resume_file_path", c.resume_file_path());
        m.put("status_note", c.status_note());
        m.put("parse_status", c.parse_status());
        m.put("parsed_at", c.parsed_at() == null ? null : c.parsed_at().toString());
        m.put("created_at", c.created_at() == null ? null : c.created_at().toString());
        m.put("updated_at", c.updated_at() == null ? null : c.updated_at().toString());
        return m;
    }
}
