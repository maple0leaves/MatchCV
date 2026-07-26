-- 精简 schema：去掉 JD 管理 / 匹配历史审核能力，users 增加昵称字段。
-- 与 V1 一致：schema 唯一归口于 Flyway。

ALTER TABLE users ADD COLUMN nickname VARCHAR(100) NOT NULL DEFAULT '' AFTER username;

DROP TABLE IF EXISTS match_sessions;
DROP TABLE IF EXISTS jds;
