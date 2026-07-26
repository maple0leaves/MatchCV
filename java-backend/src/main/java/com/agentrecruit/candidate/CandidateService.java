package com.agentrecruit.candidate;

import com.agentrecruit.ai.AiClient;
import com.agentrecruit.candidate.cache.CandidateDetailCache;
import com.agentrecruit.candidate.dto.CandidateResponse;
import com.agentrecruit.candidate.dto.CandidateUpdateRequest;
import com.agentrecruit.candidate.entity.Candidate;
import com.agentrecruit.candidate.mapper.CandidateMapper;
import com.agentrecruit.common.ApiException;
import com.agentrecruit.common.PageResponse;
import com.agentrecruit.messaging.ResumeParseDispatcher;
import com.agentrecruit.messaging.ResumeParseTaskService;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

@Slf4j
@Service
public class CandidateService {

    private static final long MAX_FILE_SIZE = 10 * 1024 * 1024;
    private static final List<DefaultResumeAsset> DEFAULT_RESUMES = List.of(
            new DefaultResumeAsset(
                    "default-resumes/lin-ruochen.pdf",
                    "default-lin-ruochen.pdf",
                    "林若辰"),
            new DefaultResumeAsset(
                    "default-resumes/zhou-zixuan.pdf",
                    "default-zhou-zixuan.pdf",
                    "周子轩"));
    // PNG/JPG 走 OCR 识别文字（见 ResumeParser#extractText），跟 PDF 共用后续的
    // 结构化解析 + 向量索引流程。
    private static final Set<String> ALLOWED_EXT = Set.of(".pdf", ".png", ".jpg", ".jpeg");
    private static final Set<String> VALID_STATUS = Set.of("new", "screening", "interview", "hired", "rejected");
    private static final Map<String, Set<String>> VALID_TRANSITIONS = Map.of(
            "new", Set.of("screening", "rejected"),
            "screening", Set.of("interview", "rejected"),
            "interview", Set.of("hired", "rejected"),
            "hired", Set.of(),
            "rejected", Set.of());

    private final CandidateMapper candidateMapper;
    private final AiClient aiClient;
    private final ResumeParseTaskService taskService;
    private final ResumeParseDispatcher dispatcher;
    private final CandidateDetailCache detailCache;
    private final String resumeDir;

    public CandidateService(CandidateMapper candidateMapper,
                            AiClient aiClient,
                            ResumeParseTaskService taskService,
                            ResumeParseDispatcher dispatcher,
                            CandidateDetailCache detailCache,
                            @Value("${app.resume.dir}") String resumeDir) {
        this.candidateMapper = candidateMapper;
        this.aiClient = aiClient;
        this.taskService = taskService;
        this.dispatcher = dispatcher;
        this.detailCache = detailCache;
        this.resumeDir = resumeDir;
    }

    public record UploadResult(CandidateResponse candidate, List<String> warnings, String filename) {
    }

    public record ResumeFile(byte[] content, String contentType, String filename) {
    }

    public record UploadFailure(String filename, String error) {
    }

    public record BatchUploadResult(List<UploadResult> items, List<UploadFailure> failures) {
    }

    private record StoredResume(String originalFilename, String ext, Path path, String relativePath) {
    }

    private record DefaultResumeAsset(String resourcePath, String storedFilename, String candidateName) {
    }

    public PageResponse<CandidateResponse> list(Long ownerUserId, int page, int pageSize,
                                                String status, String keyword) {
        LambdaQueryWrapper<Candidate> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Candidate::getOwnerUserId, ownerUserId);
        if (StringUtils.hasText(status)) {
            wrapper.eq(Candidate::getStatus, status);
        }
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(Candidate::getName, keyword)
                    .or().like(Candidate::getSkills, keyword));
        }
        wrapper.orderByDesc(Candidate::getCreatedAt);
        Page<Candidate> result = candidateMapper.selectPage(Page.of(page, pageSize), wrapper);
        List<CandidateResponse> items = result.getRecords().stream().map(CandidateResponse::from).toList();
        return new PageResponse<>(items, result.getTotal(), page, pageSize);
    }

    public CandidateResponse get(Long ownerUserId, Long id) {
        CandidateDetailCache.Lookup cached = detailCache.get(ownerUserId, id);
        if (cached.state() == CandidateDetailCache.LookupState.FOUND) {
            return cached.candidate();
        }
        if (cached.state() == CandidateDetailCache.LookupState.NOT_FOUND) {
            throw ApiException.notFound("学生不存在");
        }

        Candidate candidate = find(ownerUserId, id);
        if (candidate == null) {
            detailCache.putNotFound(ownerUserId, id);
            throw ApiException.notFound("学生不存在");
        }

        CandidateResponse response = CandidateResponse.from(candidate);
        detailCache.putIfStable(ownerUserId, id, response);
        return response;
    }

    public CandidateResponse update(Long ownerUserId, Long id, CandidateUpdateRequest req) {
        Candidate c = require(ownerUserId, id);
        if (req.name() != null) c.setName(req.name());
        if (req.email() != null) c.setEmail(req.email());
        if (req.phone() != null) c.setPhone(req.phone());
        if (req.skills() != null) c.setSkills(req.skills());
        if (req.education() != null) c.setEducation(req.education());
        if (req.experience() != null) c.setExperience(req.experience());
        if (candidateMapper.updateById(c) != 1) {
            throw ApiException.conflict("学生信息刚刚被其他操作修改，请刷新后重试");
        }
        detailCache.evict(ownerUserId, id);
        return CandidateResponse.from(require(ownerUserId, id));
    }

    public CandidateResponse updateStatus(Long ownerUserId, Long id, String newStatus, String statusNote) {
        if (!VALID_STATUS.contains(newStatus)) {
            throw ApiException.badRequest("无效的状态值: " + newStatus);
        }
        if (!StringUtils.hasText(statusNote)) {
            throw new ApiException(422, "状态变更时备注为必填项");
        }
        Candidate c = require(ownerUserId, id);
        Set<String> allowed = VALID_TRANSITIONS.getOrDefault(c.getStatus(), Set.of());
        if (!allowed.contains(newStatus)) {
            throw ApiException.badRequest(
                    String.format("无效的状态变更：无法从 %s 变更为 %s", c.getStatus(), newStatus));
        }
        c.setStatus(newStatus);
        c.setStatusNote(statusNote.strip());
        if (candidateMapper.updateById(c) != 1) {
            throw ApiException.conflict("学生状态刚刚被其他操作修改，请刷新后重试");
        }
        detailCache.evict(ownerUserId, id);
        return CandidateResponse.from(require(ownerUserId, id));
    }

    public UploadResult upload(Long ownerUserId, MultipartFile file) {
        StoredResume stored = storeResume(ownerUserId, file);

        Candidate candidate = new Candidate();
        candidate.setOwnerUserId(ownerUserId);
        candidate.setName(fallbackName(stored.originalFilename()));
        candidate.setEmail("");
        candidate.setPhone("");
        candidate.setSkills("");
        candidate.setEducation("");
        candidate.setExperience("");
        candidate.setStatus("new");
        candidate.setResumeFilePath(stored.relativePath());
        candidate.setStatusNote("简历已上传，等待后台解析");
        candidate.setParsedAt(null);

        ResumeParseTaskService.CandidateTask created;
        try {
            created = taskService.createCandidateAndTask(candidate, stored.path(), stored.ext());
        } catch (RuntimeException e) {
            deleteStoredFile(stored.path());
            throw e;
        }
        Candidate saved = candidateMapper.selectById(created.candidate().getId());
        detailCache.evict(ownerUserId, created.candidate().getId());
        dispatcher.dispatch(created.task().getId());

        return new UploadResult(CandidateResponse.from(saved), List.of(), stored.originalFilename());
    }

    public BatchUploadResult uploadBatch(Long ownerUserId, List<MultipartFile> files) {
        if (files == null || files.isEmpty()) {
            throw ApiException.badRequest("请选择要上传的简历文件");
        }

        List<UploadResult> items = new ArrayList<>();
        List<UploadFailure> failures = new ArrayList<>();

        for (MultipartFile file : files) {
            String filename = displayFilename(file);
            try {
                items.add(upload(ownerUserId, file));
            } catch (ApiException e) {
                failures.add(new UploadFailure(filename, e.getMessage()));
            } catch (Exception e) {
                log.warn("上传简历失败：{}", filename, e);
                failures.add(new UploadFailure(filename, "上传失败，请稍后重试"));
            }
        }

        return new BatchUploadResult(items, failures);
    }

    /**
     * 为新注册账号复制并解析系统内置的两份示例简历。
     *
     * 调用方注册事务提交后才投递解析任务；若事务回滚，则同步删除已经复制的
     * 文件，避免留下没有数据库记录的孤儿文件。固定文件名同时让该操作具备
     * 幂等性，不会给同一账号重复创建默认学生。
     */
    public void seedDefaultResumes(Long ownerUserId) {
        if (ownerUserId == null) {
            throw new ApiException(500, "初始化默认简历失败：账号 ID 为空");
        }
        for (DefaultResumeAsset asset : DEFAULT_RESUMES) {
            seedDefaultResume(ownerUserId, asset);
        }
    }

    private void seedDefaultResume(Long ownerUserId, DefaultResumeAsset asset) {
        String relativePath = "data/resumes/" + ownerUserId + "/" + asset.storedFilename();
        Long existing = candidateMapper.selectCount(new LambdaQueryWrapper<Candidate>()
                .eq(Candidate::getOwnerUserId, ownerUserId)
                .eq(Candidate::getResumeFilePath, relativePath));
        if (existing != null && existing > 0) {
            return;
        }

        Path rootDir = Path.of(resumeDir).toAbsolutePath().normalize();
        Path ownerDir = rootDir.resolve(String.valueOf(ownerUserId)).normalize();
        Path target = ownerDir.resolve(asset.storedFilename()).normalize();
        if (!ownerDir.startsWith(rootDir) || !target.startsWith(ownerDir)) {
            throw new ApiException(500, "默认简历保存路径非法");
        }

        try {
            Files.createDirectories(ownerDir);
            ClassPathResource resource = new ClassPathResource(asset.resourcePath());
            try (InputStream input = resource.getInputStream()) {
                Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException e) {
            log.error("复制默认简历失败：{}", asset.resourcePath(), e);
            throw new ApiException(500, "初始化默认简历失败：" + asset.candidateName());
        }
        cleanupFileIfTransactionRollsBack(target);

        Candidate candidate = new Candidate();
        candidate.setOwnerUserId(ownerUserId);
        candidate.setName(asset.candidateName());
        candidate.setEmail("");
        candidate.setPhone("");
        candidate.setSkills("");
        candidate.setEducation("");
        candidate.setExperience("");
        candidate.setStatus("new");
        candidate.setResumeFilePath(relativePath);
        candidate.setStatusNote("系统默认简历，等待后台解析");
        candidate.setParsedAt(null);

        ResumeParseTaskService.CandidateTask created;
        try {
            created = taskService.createCandidateAndTask(candidate, target, ".pdf");
        } catch (RuntimeException e) {
            if (!TransactionSynchronizationManager.isSynchronizationActive()) {
                deleteStoredFile(target);
            }
            throw e;
        }
        detailCache.evict(ownerUserId, created.candidate().getId());
        dispatchAfterCommit(created.task().getId());
    }

    private void cleanupFileIfTransactionRollsBack(Path path) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCompletion(int status) {
                if (status != TransactionSynchronization.STATUS_COMMITTED) {
                    deleteStoredFile(path);
                }
            }
        });
    }

    private void dispatchAfterCommit(Long taskId) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            dispatcher.dispatch(taskId);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                try {
                    dispatcher.dispatch(taskId);
                } catch (RuntimeException e) {
                    // 任务仍保留在 Outbox，定时扫描会继续投递，不影响注册结果。
                    log.warn("默认简历解析任务首次投递失败，等待 Outbox 重试，taskId={}", taskId, e);
                }
            }
        });
    }

    public void delete(Long ownerUserId, Long id) {
        Candidate candidate = require(ownerUserId, id);
        taskService.cancelForCandidate(id);
        candidateMapper.deleteById(id);
        detailCache.evict(ownerUserId, id);
        deleteResumeFile(ownerUserId, candidate.getResumeFilePath());
        boolean unindexed = aiClient.unindexCandidate(ownerUserId, candidate.getResumeFilePath());
        if (unindexed) {
            log.info("已从向量库删除候选人向量，candidateId={}", id);
        } else {
            log.warn("从向量库删除候选人向量失败或无向量记录，candidateId={}", id);
        }
    }

    /** 读取候选人原始简历文件，供前端预览/下载。 */
    public ResumeFile resumeFile(Long ownerUserId, Long id) {
        Candidate candidate = require(ownerUserId, id);
        String resumeFilePath = candidate.getResumeFilePath();
        if (!StringUtils.hasText(resumeFilePath)) {
            throw ApiException.notFound("该学生暂无原始简历文件");
        }
        return loadResumeFile(ownerUserId, resumeFilePath, candidate.getName());
    }

    /**
     * 按简历文件路径直接定位并读取原始文件，供"智能匹配结果"页按 AI 返回的
     * resume_source 预览用。resume_source 的值与 candidate.resumeFilePath 是
     * 同一份数据——Java 侧同步候选人到向量库时，就是把 resumeFilePath 原样
     * 当作 source 传给 Python 的，所以这里复用与按 id 查询完全一致的安全校验
     * （只取文件名、限定在 resumeDir 内解析），不会引入任意路径读取风险。
     */
    public ResumeFile resumeFileBySource(Long ownerUserId, String source) {
        if (!StringUtils.hasText(source)) {
            throw ApiException.badRequest("缺少简历文件路径");
        }
        Candidate candidate = candidateMapper.selectOne(new LambdaQueryWrapper<Candidate>()
                .eq(Candidate::getOwnerUserId, ownerUserId)
                .eq(Candidate::getResumeFilePath, source)
                .last("LIMIT 1"));
        if (candidate == null) {
            throw ApiException.notFound("学生简历不存在");
        }
        return loadResumeFile(ownerUserId, candidate.getResumeFilePath(), candidate.getName());
    }

    /**
     * 候选人重新提交一次异步简历解析任务。
     * 复用上传时的完整解析链路，并通过 parseVersion 防止旧任务覆盖新结果。
     */
    public CandidateResponse reparse(Long ownerUserId, Long id) {
        Candidate candidate = require(ownerUserId, id);
        if (!StringUtils.hasText(candidate.getResumeFilePath())) {
            throw ApiException.badRequest("该学生暂无原始简历文件，无法重新解析");
        }
        Path target = resolveStoredFile(ownerUserId, candidate.getResumeFilePath());
        String ext = extension(target.getFileName().toString());
        ResumeParseTaskService.CandidateTask created =
                taskService.createReparseTask(ownerUserId, id, target, ext);
        detailCache.evict(ownerUserId, id);
        dispatcher.dispatch(created.task().getId());
        return CandidateResponse.from(created.candidate());
    }

    private Path resolveStoredFile(Long ownerUserId, String resumeFilePath) {
        Path dir = Path.of(resumeDir).toAbsolutePath().normalize();
        Path storedName;
        try {
            storedName = Path.of(resumeFilePath).getFileName();
        } catch (InvalidPathException e) {
            storedName = null;
        }
        if (storedName == null) {
            throw ApiException.notFound("原始简历文件不存在或已被删除");
        }
        Path ownerDir = dir.resolve(String.valueOf(ownerUserId)).normalize();
        Path target = ownerDir.resolve(storedName.toString()).normalize();
        if (!target.startsWith(ownerDir) || !Files.exists(target)) {
            // V3 迁移前的历史简历存放在根目录；其数据库记录已归属历史管理员。
            target = dir.resolve(storedName.toString()).normalize();
        }
        if (!target.startsWith(dir) || !Files.exists(target)) {
            throw ApiException.notFound("原始简历文件不存在或已被删除");
        }
        return target;
    }

    private ResumeFile loadResumeFile(Long ownerUserId, String resumeFilePath, String preferredName) {
        Path target = resolveStoredFile(ownerUserId, resumeFilePath);

        byte[] content;
        try {
            content = Files.readAllBytes(target);
        } catch (IOException e) {
            throw new ApiException(500, "读取简历文件失败：" + e.getMessage());
        }

        String ext = extension(target.getFileName().toString());
        String contentType = switch (ext) {
            case ".pdf" -> "application/pdf";
            case ".png" -> "image/png";
            case ".jpg", ".jpeg" -> "image/jpeg";
            default -> "application/octet-stream";
        };
        String safeName = StringUtils.hasText(preferredName)
                ? preferredName.replaceAll("[\\\\/:*?\"<>|]", "_")
                : "resume";
        return new ResumeFile(content, contentType, truncate(safeName, 100) + ext);
    }

    private StoredResume storeResume(Long ownerUserId, MultipartFile file) {
        String filename = displayFilename(file);
        String ext = extension(filename);
        if (!ALLOWED_EXT.contains(ext)) {
            throw ApiException.badRequest("仅支持 PDF / PNG / JPG 格式，不支持 " + ext + " 文件。");
        }

        byte[] raw;
        try {
            raw = file.getBytes();
        } catch (IOException e) {
            throw ApiException.badRequest("读取文件失败");
        }
        if (raw.length == 0) {
            throw ApiException.badRequest("文件内容为空");
        }
        if (raw.length > MAX_FILE_SIZE) {
            throw ApiException.badRequest("文件大小不能超过 10MB");
        }

        String safeName = UUID.randomUUID().toString().replace("-", "") + ext;
        Path rootDir = Path.of(resumeDir).toAbsolutePath().normalize();
        Path ownerDir = rootDir.resolve(String.valueOf(ownerUserId)).normalize();
        Path target = ownerDir.resolve(safeName).normalize();
        if (!ownerDir.startsWith(rootDir) || !target.startsWith(ownerDir)) {
            throw new ApiException(500, "简历保存路径非法");
        }

        try {
            Files.createDirectories(ownerDir);
            Files.write(target, raw);
        } catch (IOException e) {
            throw new ApiException(500, "保存简历文件失败：" + e.getMessage());
        }

        return new StoredResume(filename, ext, target,
                "data/resumes/" + ownerUserId + "/" + safeName);
    }

    private void deleteResumeFile(Long ownerUserId, String resumeFilePath) {
        if (!StringUtils.hasText(resumeFilePath)) {
            return;
        }

        try {
            Path dir = Path.of(resumeDir).toAbsolutePath().normalize();
            Path target = resolveStoredFile(ownerUserId, resumeFilePath);
            if (!target.startsWith(dir)) {
                log.warn("跳过删除非法简历路径：{}", resumeFilePath);
                return;
            }
            Files.deleteIfExists(target);
        } catch (ApiException e) {
            log.info("简历文件已不存在，跳过删除：{}", resumeFilePath);
        } catch (IOException | InvalidPathException e) {
            log.warn("删除简历文件失败：{}", resumeFilePath, e);
        }
    }

    private void deleteStoredFile(Path path) {
        try {
            Files.deleteIfExists(path);
        } catch (IOException e) {
            log.warn("数据库事务失败后清理简历文件失败：{}", path, e);
        }
    }

    private Candidate require(Long ownerUserId, Long id) {
        Candidate c = find(ownerUserId, id);
        if (c == null) {
            throw ApiException.notFound("学生不存在");
        }
        return c;
    }

    private Candidate find(Long ownerUserId, Long id) {
        return candidateMapper.selectOne(new LambdaQueryWrapper<Candidate>()
                .eq(Candidate::getId, id)
                .eq(Candidate::getOwnerUserId, ownerUserId)
                .last("LIMIT 1"));
    }

    private static String displayFilename(MultipartFile file) {
        String filename = file == null ? null : file.getOriginalFilename();
        if (!StringUtils.hasText(filename)) {
            return "resume.pdf";
        }
        String normalized = filename.replace("\\", "/");
        return normalized.substring(normalized.lastIndexOf('/') + 1);
    }

    private static String fallbackName(String filename) {
        String name = filename;
        int dot = name.lastIndexOf('.');
        if (dot > 0) {
            name = name.substring(0, dot);
        }
        name = name.strip();
        if (!StringUtils.hasText(name)) {
            return "解析中学生";
        }
        return truncate(name, 200);
    }

    private static String extension(String filename) {
        int dot = filename.lastIndexOf('.');
        return dot < 0 ? "" : filename.substring(dot).toLowerCase();
    }

    private static String truncate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }
}
