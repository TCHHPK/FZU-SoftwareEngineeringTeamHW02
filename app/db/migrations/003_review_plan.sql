-- 003_review_plan.sql —— v1.3.0 Beta：错题排期（K4）与执行轨迹（K5）
--
-- 说明：本文件只做「可用 IF NOT EXISTS 保证幂等」的部分——新建表与索引。
--       wrong_questions 的六个调度字段（state / stability / difficulty /
--       due_at / review_count / last_review_at）写在 app/db/conn.py 的
--       _BUSINESS_MIGRATIONS 里，因为 SQLite 的 ALTER TABLE ADD COLUMN
--       不支持 IF NOT EXISTS，重复执行会报 duplicate column；
--       那边用「先查 PRAGMA table_info 再 ALTER」保证老库可反复升级。
--
-- 老库升级：init_databases()（不要加 --reset），迁移自动执行。

-- ---------------------------------------------------------------- K4 错题排期
-- state: new / learning / review / relearning
-- stability / difficulty: FSRS 记忆参数（由 fsrs 库计算后回写）
-- due_at: 下次到期时间（ISO8601 字符串，UTC）
-- review_count / last_review_at: 复习次数与最近一次复习时间
--
-- 这里的 ALTER 仅为全新库预留注释说明，实际字段由 conn._BUSINESS_MIGRATIONS 添加。

CREATE INDEX IF NOT EXISTS idx_wq_due
    ON wrong_questions (user_id, due_at);

CREATE INDEX IF NOT EXISTS idx_wq_state
    ON wrong_questions (user_id, state);

-- ---------------------------------------------------------------- K5 执行轨迹
-- 一次整理任务的阶段流水线记录，由 ProgressReporter.report 逐条写入。
-- detail_json 只存工具名、耗时、证据通过与丢弃条数，不存模型原文（控体积、避隐私）。
CREATE TABLE IF NOT EXISTS session_traces (
    trace_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL,
    seq         INTEGER NOT NULL DEFAULT 0,
    stage       TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'running',
    message     TEXT    NOT NULL DEFAULT '',
    detail_json TEXT    NOT NULL DEFAULT '{}',
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_trace_session
    ON session_traces (session_id, seq);
