package com.studentadmission.student;

import com.studentadmission.student.dto.StudentResponse;
import com.studentadmission.student.dto.StudentStatusUpdateRequest;
import com.studentadmission.student.dto.StudentUpdateRequest;
import com.studentadmission.common.PageResponse;
import com.studentadmission.security.AuthUser;
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
@RequestMapping("/api/students")
public class StudentController {

    private final StudentService studentService;

    public StudentController(StudentService studentService) {
        this.studentService = studentService;
    }

    @PostMapping("/upload")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> upload(@AuthenticationPrincipal AuthUser user,
                                      @RequestParam("file") MultipartFile file) {
        StudentService.UploadResult result = studentService.upload(currentUserId(user), file);
        Map<String, Object> body = toUploadMap(result);
        return body;
    }

    @PostMapping("/upload/batch")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> uploadBatch(@AuthenticationPrincipal AuthUser user,
                                           @RequestParam("files") List<MultipartFile> files) {
        StudentService.BatchUploadResult result = studentService.uploadBatch(currentUserId(user), files);
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

    private Map<String, Object> toUploadMap(StudentService.UploadResult result) {
        Map<String, Object> body = new LinkedHashMap<>(toMap(result.student()));
        body.put("filename", result.filename());
        if (!result.warnings().isEmpty()) {
            body.put("warnings", result.warnings());
        }
        return body;
    }

    @GetMapping
    public PageResponse<StudentResponse> list(
            @AuthenticationPrincipal AuthUser user,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(name = "page_size", defaultValue = "20") int pageSize,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String keyword) {
        return studentService.list(currentUserId(user), page, pageSize, status, keyword);
    }

    @GetMapping("/{id}")
    public StudentResponse get(@AuthenticationPrincipal AuthUser user, @PathVariable Long id) {
        return studentService.get(currentUserId(user), id);
    }

    @PutMapping("/{id}")
    public StudentResponse update(@AuthenticationPrincipal AuthUser user,
                                    @PathVariable Long id,
                                    @RequestBody StudentUpdateRequest request) {
        return studentService.update(currentUserId(user), id, request);
    }


    @GetMapping("/{id}/resume-file")
    public ResponseEntity<byte[]> resumeFile(@AuthenticationPrincipal AuthUser user, @PathVariable Long id) {
        return toResumeFileResponse(studentService.resumeFile(currentUserId(user), id));
    }





    @GetMapping("/resume-file")
    public ResponseEntity<byte[]> resumeFileBySource(@AuthenticationPrincipal AuthUser user,
                                                     @RequestParam String source) {
        return toResumeFileResponse(studentService.resumeFileBySource(currentUserId(user), source));
    }

    private ResponseEntity<byte[]> toResumeFileResponse(StudentService.ResumeFile file) {
        String encodedName = URLEncoder.encode(file.filename(), StandardCharsets.UTF_8).replace("+", "%20");
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(file.contentType()))
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "inline; filename=\"" + file.filename() + "\"; filename*=UTF-8''" + encodedName)
                .body(file.content());
    }


    @PostMapping("/{id}/reparse")
    public StudentResponse reparse(@AuthenticationPrincipal AuthUser user, @PathVariable Long id) {
        return studentService.reparse(currentUserId(user), id);
    }

    @PatchMapping("/{id}/status")
    public StudentResponse updateStatus(@AuthenticationPrincipal AuthUser user,
                                          @PathVariable Long id,
                                          @Valid @RequestBody StudentStatusUpdateRequest request) {
        return studentService.updateStatus(
                currentUserId(user), id, request.status(), request.status_note());
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@AuthenticationPrincipal AuthUser user, @PathVariable Long id) {
        studentService.delete(currentUserId(user), id);
    }

    private static Long currentUserId(AuthUser user) {
        if (user == null || user.userId() == null) {
            throw new IllegalStateException("认证用户信息缺失");
        }
        return Long.valueOf(user.userId());
    }

    private Map<String, Object> toMap(StudentResponse c) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", c.id());
        m.put("name", c.name());
        m.put("email", c.email());
        m.put("phone", c.phone());
        m.put("skills", c.skills());
        m.put("education", c.education());
        m.put("research_experience", c.research_experience());
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
