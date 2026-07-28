package com.studentadmission.messaging;

import com.studentadmission.student.cache.StudentDetailCache;
import com.studentadmission.student.entity.Student;
import com.studentadmission.student.mapper.StudentMapper;
import com.studentadmission.common.ApiException;
import com.studentadmission.messaging.entity.ResumeParseTask;
import com.studentadmission.messaging.mapper.ResumeParseTaskMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static com.studentadmission.messaging.ResumeParseTaskStates.CANCELLED;
import static com.studentadmission.messaging.ResumeParseTaskStates.DEAD;
import static com.studentadmission.messaging.ResumeParseTaskStates.FAILED;
import static com.studentadmission.messaging.ResumeParseTaskStates.MQ_PENDING;
import static com.studentadmission.messaging.ResumeParseTaskStates.MQ_SENT;
import static com.studentadmission.messaging.ResumeParseTaskStates.PENDING;
import static com.studentadmission.messaging.ResumeParseTaskStates.PROCESSING;
import static com.studentadmission.messaging.ResumeParseTaskStates.SUCCESS;

@Service
public class ResumeParseTaskService {

    private final StudentMapper studentMapper;
    private final ResumeParseTaskMapper taskMapper;
    private final StudentDetailCache detailCache;

    public ResumeParseTaskService(StudentMapper studentMapper,
                                  ResumeParseTaskMapper taskMapper,
                                  StudentDetailCache detailCache) {
        this.studentMapper = studentMapper;
        this.taskMapper = taskMapper;
        this.detailCache = detailCache;
    }

    public record StudentTask(Student student, ResumeParseTask task) {
    }

    @Transactional
    public StudentTask createStudentAndTask(Student student, Path resumePath, String ext) {
        student.setVersion(0);
        student.setParseVersion(1);
        student.setParseStatus("pending");
        studentMapper.insert(student);

        ResumeParseTask task = newTask(student, resumePath, ext);
        taskMapper.insert(task);
        return new StudentTask(student, task);
    }

    @Transactional
    public StudentTask createReparseTask(Long ownerUserId, Long studentId, Path resumePath, String ext) {
        Student student = requireStudent(ownerUserId, studentId);
        int nextVersion = Optional.ofNullable(student.getParseVersion()).orElse(0) + 1;
        student.setParseVersion(nextVersion);
        student.setParseStatus("pending");
        student.setParsedAt(null);
        student.setStatusNote("已提交重新解析任务");
        if (studentMapper.updateById(student) != 1) {
            throw ApiException.conflict("学生信息刚刚被其他操作修改，请刷新后重试");
        }

        ResumeParseTask task = newTask(student, resumePath, ext);
        taskMapper.insert(task);
        return new StudentTask(studentMapper.selectById(studentId), task);
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
            updateStudentParseState(task, "failed", truncate(error), false);
        }
    }

    public void markDead(ResumeParseTask task, String error) {
        if (finish(task, DEAD, error)) {
            updateStudentParseState(task, "failed", "解析重试次数已耗尽：" + truncate(error), false);
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

    public void cancelForStudent(Long studentId) {
        taskMapper.update(null, new LambdaUpdateWrapper<ResumeParseTask>()
                .eq(ResumeParseTask::getStudentId, studentId)
                .in(ResumeParseTask::getTaskStatus, List.of(PENDING, PROCESSING))
                .set(ResumeParseTask::getTaskStatus, CANCELLED)
                .set(ResumeParseTask::getCompletedAt, LocalDateTime.now()));
    }

    private ResumeParseTask newTask(Student student, Path resumePath, String ext) {
        ResumeParseTask task = new ResumeParseTask();
        task.setStudentId(student.getId());
        task.setOwnerUserId(student.getOwnerUserId());
        task.setParseVersion(student.getParseVersion());
        task.setResumePath(resumePath.toAbsolutePath().normalize().toString());
        task.setFileExt(ext);
        task.setTaskStatus(PENDING);
        task.setMqStatus(MQ_PENDING);
        task.setDeliveryAttempts(0);
        task.setConsumeAttempts(0);
        task.setErrorMessage("");
        return task;
    }

    private Student requireStudent(Long ownerUserId, Long studentId) {
        Student student = studentMapper.selectOne(new LambdaQueryWrapper<Student>()
                .eq(Student::getId, studentId)
                .eq(Student::getOwnerUserId, ownerUserId)
                .last("LIMIT 1"));
        if (student == null) {
            throw ApiException.notFound("学生不存在");
        }
        return student;
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
            updateStudentParseState(task, "pending", "解析暂时失败，正在重试", false);
        }
    }

    public void updateStudentParseState(ResumeParseTask task,
                                          String parseStatus,
                                          String note,
                                          boolean parsed) {
        LambdaUpdateWrapper<Student> update = new LambdaUpdateWrapper<Student>()
                .eq(Student::getId, task.getStudentId())
                .eq(Student::getParseVersion, task.getParseVersion())
                .set(Student::getParseStatus, parseStatus)
                .set(Student::getStatusNote, truncate(note));
        if (!parsed) {
            update.set(Student::getParsedAt, null);
        }
        if (studentMapper.update(null, update) == 1) {
            detailCache.evict(task.getOwnerUserId(), task.getStudentId());
        }
    }

    private static String truncate(String value) {
        if (value == null) {
            return "";
        }
        return value.length() <= 1000 ? value : value.substring(0, 1000);
    }
}
