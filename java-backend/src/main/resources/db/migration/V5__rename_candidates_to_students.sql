


RENAME TABLE candidates TO students;

ALTER TABLE students
    RENAME COLUMN experience TO research_experience,
    DROP FOREIGN KEY fk_candidates_owner,
    DROP INDEX idx_candidates_name,
    DROP INDEX idx_candidates_status,
    DROP INDEX idx_candidates_owner_created,
    DROP INDEX idx_candidates_owner_status_created,
    DROP INDEX idx_candidates_owner_resume_path,
    ADD KEY idx_students_name (name),
    ADD KEY idx_students_status (status),
    ADD KEY idx_students_owner_created (owner_user_id, created_at),
    ADD KEY idx_students_owner_status_created (owner_user_id, status, created_at),
    ADD KEY idx_students_owner_resume_path (owner_user_id, resume_file_path),
    ADD CONSTRAINT fk_students_owner
        FOREIGN KEY (owner_user_id) REFERENCES users(id)
        ON DELETE RESTRICT;

ALTER TABLE resume_parse_tasks
    DROP FOREIGN KEY fk_resume_parse_candidate,
    RENAME COLUMN candidate_id TO student_id,
    DROP INDEX uk_resume_parse_candidate_version,
    ADD UNIQUE KEY uk_resume_parse_student_version (student_id, parse_version),
    ADD CONSTRAINT fk_resume_parse_student
        FOREIGN KEY (student_id) REFERENCES students(id)
        ON DELETE CASCADE;

UPDATE students
SET status = CASE status
    WHEN 'screening' THEN 'reviewing'
    WHEN 'interview' THEN 'recommended_interview'
    WHEN 'hired' THEN 'admitted'
    WHEN 'rejected' THEN 'not_recommended'
    ELSE status
END;

UPDATE users
SET role = 'supervisor'
WHERE role = 'recruiter';
