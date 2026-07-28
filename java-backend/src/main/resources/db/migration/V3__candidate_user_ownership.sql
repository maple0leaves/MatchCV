




ALTER TABLE candidates
    ADD COLUMN owner_user_id INT NULL AFTER id;

UPDATE candidates
SET owner_user_id = (
    SELECT id
    FROM users
    ORDER BY (role = 'admin') DESC, (username = 'admin') DESC, id ASC
    LIMIT 1
)
WHERE owner_user_id IS NULL;

ALTER TABLE candidates
    MODIFY COLUMN owner_user_id INT NOT NULL,
    ADD KEY idx_candidates_owner_created (owner_user_id, created_at),
    ADD KEY idx_candidates_owner_status (owner_user_id, status),
    ADD CONSTRAINT fk_candidates_owner
        FOREIGN KEY (owner_user_id) REFERENCES users(id)
        ON DELETE RESTRICT;
