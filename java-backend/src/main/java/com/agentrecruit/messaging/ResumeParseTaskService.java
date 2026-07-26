package com.agentrecruit.messaging;

import com.agentrecruit.candidate.cache.CandidateDetailCache;
import com.agentrecruit.candidate.entity.Candidate;
import com.agentrecruit.candidate.mapper.CandidateMapper;
import com.agentrecruit.common.ApiException;
import com.agentrecruit.messaging.entity.ResumeParseTask;
import com.agentrecruit.messaging.mapper.ResumeParseTaskMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static com.agentrecruit.messaging.ResumeParseTaskStates.CANCELLED;
import static com.agentrecruit.messaging.ResumeParseTaskStates.DEAD;
import static com.agentrecruit.messaging.ResumeParseTaskStates.FAILED;
import static com.agentrecruit.messaging.ResumeParseTaskStates.MQ_PENDING;
import static com.agentrecruit.messaging.ResumeParseTaskStates.MQ_SENT;
import static com.agentrecruit.messaging.ResumeParseTaskStates.PENDING;
import static com.agentrecruit.messaging.ResumeParseTaskStates.PROCESSING;
import static com.agentrecruit.messaging.ResumeParseTaskStates.SUCCESS;

@Service
public class ResumeParseTaskService {

    private final CandidateMapper candidateMapper;
    private final ResumeParseTaskMapper taskMapper;
    private final CandidateDetailCache detailCache;

    public ResumeParseTaskService(CandidateMapper candidateMapper,
                                  ResumeParseTaskMapper taskMapper,
                                  CandidateDetailCache detailCache) {
        this.candidateMapper = candidateMapper;
        this.taskMapper = taskMapper;
        this.detailCache = detailCache;
    }

    public record CandidateTask(Candidate candidate, ResumeParseTask task) {
    }

    @Transactional
    public CandidateTask createCandidateAndTask(Candidate candidate, Path resumePath, String ext) {
        candidate.setVersion(0);
        candidate.setParseVersion(1);
        candidate.setParseStatus("pending");
        candidateMapper.insert(candidate);

        ResumeParseTask task = newTask(candidate, resumePath, ext);
        taskMapper.insert(task);
        return new CandidateTask(candidate, task);
    }

    @Transactional
    public CandidateTask createReparseTask(Long ownerUserId, Long candidateId, Path resumePath, String ext) {
        Candidate candidate = requireCandidate(ownerUserId, candidateId);
        int nextVersion = Optional.ofNullable(candidate.getParseVersion()).orElse(0) + 1;
        candidate.setParseVersion(nextVersion);
        candidate.setParseStatus("pending");
        candidate.setParsedAt(null);
        candidate.setStatusNote("已提交重新解析任务");
        if (candidateMapper.updateById(candidate) != 1) {
            throw ApiException.conflict("学生信息刚刚被其他操作修改，请刷新后重试");
        }

        ResumeParseTask task = newTask(candidate, resumePath, ext);
        taskMapper.insert(task);
        return new CandidateTask(candidateMapper.selectById(candidateId), task);
    }

    public Optional<ResumeParseTask> claim(Long taskId) {
        LocalDateTime now = LocalDateTime.now();
        int updated = taskMapper.update(null, new LambdaUpdateWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getId, taskId)
                .eq(ResumeParseTask::getTaskStatus, PENDING)
                .set(ResumeParseTask::getTaskStatus, PROCESSING)
                .set(ResumeParseTask::getStartedAt, now)
                .set(ResumeParseTask::getErrorMessage, "")
                .setSql("consume_attempts = consume_attempts + 1"));
        return updated == 1 ? Optional.ofNullable(taskMapper.selectById(taskId)) : Optional.empty();
    }

    public ResumeParseTask get(Long taskId) {
        return taskMapper.selectById(taskId);
    }

    public List<ResumeParseTask> pendingDeliveries(int limit) {
        LocalDateTime now = LocalDateTime.now();
        return taskMapper.selectList(new LambdaQueryWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getTaskStatus, PENDING)
                .eq(ResumeParseTask::getMqStatus, MQ_PENDING)
                .and(w -> w.isNull(ResumeParseTask::getNextDeliveryAt)
                        .or().le(ResumeParseTask::getNextDeliveryAt, now))
                .orderByAsc(ResumeParseTask::getId)
                .last("LIMIT " + Math.max(1, limit)));
    }

    public void markMqSent(Long taskId) {
        taskMapper.update(null, new LambdaUpdateWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getId, taskId)
                .eq(ResumeParseTask::getMqStatus, MQ_PENDING)
                .set(ResumeParseTask::getMqStatus, MQ_SENT)
                .set(ResumeParseTask::getNextDeliveryAt, null)
                .setSql("delivery_attempts = delivery_attempts + 1"));
    }

    public void markDeliveryFailed(Long taskId, String error, LocalDateTime nextAttempt) {
        taskMapper.update(null, new LambdaUpdateWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getId, taskId)
                .eq(ResumeParseTask::getTaskStatus, PENDING)
                .set(ResumeParseTask::getMqStatus, MQ_PENDING)
                .set(ResumeParseTask::getNextDeliveryAt, nextAttempt)
                .set(ResumeParseTask::getErrorMessage, truncate(error))
                .setSql("delivery_attempts = delivery_attempts + 1"));
    }

    public void markSuccess(ResumeParseTask task) {
        finish(task, SUCCESS, "");
    }

    public void markFailed(ResumeParseTask task, String error) {
        if (finish(task, FAILED, error)) {
            updateCandidateParseState(task, "failed", truncate(error), false);
        }
    }

    public void markDead(ResumeParseTask task, String error) {
        if (finish(task, DEAD, error)) {
            updateCandidateParseState(task, "failed", "解析重试次数已耗尽：" + truncate(error), false);
        }
    }

    public void releaseForMqRetry(ResumeParseTask task, String error) {
        releaseForRetry(task, error, MQ_SENT);
    }

    public void releaseForOutboxRetry(ResumeParseTask task, String error) {
        releaseForRetry(task, error, MQ_PENDING);
    }

    public int recoverStaleProcessing(LocalDateTime cutoff) {
        return taskMapper.update(null, new LambdaUpdateWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getTaskStatus, PROCESSING)
                .lt(ResumeParseTask::getUpdatedAt, cutoff)
                .set(ResumeParseTask::getTaskStatus, PENDING)
                .set(ResumeParseTask::getMqStatus, MQ_PENDING)
                .set(ResumeParseTask::getNextDeliveryAt, LocalDateTime.now())
                .set(ResumeParseTask::getErrorMessage, "检测到超时未完成任务，已重新排队"));
    }

    public void cancelForCandidate(Long candidateId) {
        taskMapper.update(null, new LambdaUpdateWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getCandidateId, candidateId)
                .in(ResumeParseTask::getTaskStatus, List.of(PENDING, PROCESSING))
                .set(ResumeParseTask::getTaskStatus, CANCELLED)
                .set(ResumeParseTask::getCompletedAt, LocalDateTime.now()));
    }

    private ResumeParseTask newTask(Candidate candidate, Path resumePath, String ext) {
        ResumeParseTask task = new ResumeParseTask();
        task.setCandidateId(candidate.getId());
        task.setOwnerUserId(candidate.getOwnerUserId());
        task.setParseVersion(candidate.getParseVersion());
        task.setResumePath(resumePath.toAbsolutePath().normalize().toString());
        task.setFileExt(ext);
        task.setTaskStatus(PENDING);
        task.setMqStatus(MQ_PENDING);
        task.setDeliveryAttempts(0);
        task.setConsumeAttempts(0);
        task.setErrorMessage("");
        return task;
    }

    private Candidate requireCandidate(Long ownerUserId, Long candidateId) {
        Candidate candidate = candidateMapper.selectOne(new LambdaQueryWrapper<Candidate>()
                .eq(Candidate::getId, candidateId)
                .eq(Candidate::getOwnerUserId, ownerUserId)
                .last("LIMIT 1"));
        if (candidate == null) {
            throw ApiException.notFound("学生不存在");
        }
        return candidate;
    }

    private boolean finish(ResumeParseTask task, String status, String error) {
        return taskMapper.update(null, new LambdaUpdateWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getId, task.getId())
                .eq(ResumeParseTask::getTaskStatus, PROCESSING)
                .set(ResumeParseTask::getTaskStatus, status)
                .set(ResumeParseTask::getCompletedAt, LocalDateTime.now())
                .set(ResumeParseTask::getErrorMessage, truncate(error))) == 1;
    }

    private void releaseForRetry(ResumeParseTask task, String error, String mqStatus) {
        int updated = taskMapper.update(null, new LambdaUpdateWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getId, task.getId())
                .eq(ResumeParseTask::getTaskStatus, PROCESSING)
                .set(ResumeParseTask::getTaskStatus, PENDING)
                .set(ResumeParseTask::getMqStatus, mqStatus)
                .set(ResumeParseTask::getNextDeliveryAt, LocalDateTime.now().plusSeconds(5))
                .set(ResumeParseTask::getErrorMessage, truncate(error)));
        if (updated == 1) {
            updateCandidateParseState(task, "pending", "解析暂时失败，正在重试", false);
        }
    }

    public void updateCandidateParseState(ResumeParseTask task,
                                          String parseStatus,
                                          String note,
                                          boolean parsed) {
        LambdaUpdateWrapper<Candidate> update = new LambdaUpdateWrapper<Candidate>()
                .eq(Candidate::getId, task.getCandidateId())
                .eq(Candidate::getParseVersion, task.getParseVersion())
                .set(Candidate::getParseStatus, parseStatus)
                .set(Candidate::getStatusNote, truncate(note));
        if (!parsed) {
            update.set(Candidate::getParsedAt, null);
        }
        if (candidateMapper.update(null, update) == 1) {
            detailCache.evict(task.getOwnerUserId(), task.getCandidateId());
        }
    }

    private static String truncate(String value) {
        if (value == null) {
            return "";
        }
        return value.length() <= 1000 ? value : value.substring(0, 1000);
    }
}
