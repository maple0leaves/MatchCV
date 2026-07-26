-- 每个候选人归属于一个用户：所有账号功能相同，但只能访问自己的候选人库。
--
-- 历史数据统一归属现有种子管理员账号。优先选择 role=admin / username=admin，
-- 若旧环境改过管理员用户名，则退化为最早创建的用户。

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
