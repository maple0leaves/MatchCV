



CREATE TABLE IF NOT EXISTS users (
    id              INT          NOT NULL AUTO_INCREMENT,
    username        VARCHAR(100) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role            VARCHAR(30)  NOT NULL DEFAULT 'recruiter',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_users_username (username)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS jds (
    id               INT           NOT NULL AUTO_INCREMENT,
    title            VARCHAR(200)  NOT NULL,
    department       VARCHAR(100)  NOT NULL,
    skills           VARCHAR(1000) NOT NULL,
    experience_years INT           NOT NULL DEFAULT 0,
    education        VARCHAR(20)   NOT NULL DEFAULT '不限',
    salary_min       INT           NOT NULL,
    salary_max       INT           NOT NULL,
    description      TEXT          NOT NULL,
    status           VARCHAR(20)   NOT NULL DEFAULT 'draft',
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_jds_title (title),
    KEY idx_jds_status (status)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS candidates (
    id               INT           NOT NULL AUTO_INCREMENT,
    name             VARCHAR(200)  NOT NULL,
    email            VARCHAR(200)  NOT NULL DEFAULT '',
    phone            VARCHAR(50)   NOT NULL DEFAULT '',
    skills           VARCHAR(2000) NOT NULL DEFAULT '',
    education        VARCHAR(500)  NOT NULL DEFAULT '',
    experience       TEXT          NULL,
    status           VARCHAR(20)   NOT NULL DEFAULT 'new',
    resume_file_path VARCHAR(500)  NOT NULL DEFAULT '',
    status_note      VARCHAR(1000) NOT NULL DEFAULT '',
    parsed_at        DATETIME      NULL,
    created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_candidates_name (name),
    KEY idx_candidates_status (status)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS match_sessions (
    id               INT          NOT NULL AUTO_INCREMENT,
    jd_id            INT          NULL,
    candidate_id     INT          NULL,
    thread_id        VARCHAR(100) NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    total_candidates INT          NOT NULL DEFAULT 0,
    approved_count   INT          NOT NULL DEFAULT 0,
    rejected_count   INT          NOT NULL DEFAULT 0,
    results_json     TEXT         NULL,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_match_thread (thread_id),
    KEY idx_match_jd (jd_id),
    KEY idx_match_candidate (candidate_id),
    KEY idx_match_status (status)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
