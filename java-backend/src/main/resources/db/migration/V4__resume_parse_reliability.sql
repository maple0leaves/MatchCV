-- Candidate concurrency control and durable resume-parse task/outbox.

ALTER TABLE candidates
    ADD COLUMN version INT NOT NULL DEFAULT 0 AFTER owner_user_id,
    ADD COLUMN parse_version INT NOT NULL DEFAULT 0 AFTER status_note,
    ADD COLUMN parse_status VARCHAR(20) NOT NULL DEFAULT 'pending' AFTER parse_version;

UPDATE candidates
SET parse_status = CASE
    WHEN parsed_at IS NOT NULL THEN 'parsed'
    ELSE 'failed'
END;

ALTER TABLE candidates
    DROP INDEX idx_candidates_owner_status,
    ADD KEY idx_candidates_owner_status_created (owner_user_id, status, created_at),
    ADD KEY idx_candidates_owner_resume_path (owner_user_id, resume_file_path);

CREATE TABLE resume_parse_tasks (
    id                  BIGINT       NOT NULL AUTO_INCREMENT,
    candidate_id        INT          NOT NULL,
    owner_user_id       INT          NOT NULL,
    parse_version       INT          NOT NULL,
    resume_path         VARCHAR(1000) NOT NULL,
    file_ext            VARCHAR(16)  NOT NULL,
    task_status         VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    mq_status           VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    delivery_attempts   INT          NOT NULL DEFAULT 0,
    consume_attempts    INT          NOT NULL DEFAULT 0,
    next_delivery_at    DATETIME     NULL,
    error_message       VARCHAR(1000) NOT NULL DEFAULT '',
    started_at          DATETIME     NULL,
    completed_at        DATETIME     NULL,
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_resume_parse_candidate_version (candidate_id, parse_version),
    KEY idx_resume_parse_delivery (mq_status, task_status, next_delivery_at, id),
    KEY idx_resume_parse_recovery (task_status, updated_at),
    CONSTRAINT fk_resume_parse_candidate
        FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_resume_parse_owner
        FOREIGN KEY (owner_user_id) REFERENCES users(id)
        ON DELETE RESTRICT
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
