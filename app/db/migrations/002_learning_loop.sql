-- 学习闭环增量迁移：与《三功能开发分工与接口契约》3.1–3.4 保持一致。
-- 仅针对 business.db；可重复执行，不触碰现有数据。

-- U14 智能自测主表
CREATE TABLE IF NOT EXISTS self_tests (
    test_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id     INTEGER REFERENCES sessions(session_id) ON DELETE SET NULL,
    course_name    TEXT NOT NULL DEFAULT '',
    scope_text     TEXT NOT NULL DEFAULT '',
    question_count INTEGER NOT NULL DEFAULT 5,
    status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'ready', 'submitted', 'graded', 'failed')),
    total_score    REAL NOT NULL DEFAULT 0,
    score          REAL NOT NULL DEFAULT 0,
    correct_count  INTEGER NOT NULL DEFAULT 0,
  error_message  TEXT    NOT NULL DEFAULT '',   -- 出题失败原因（自测接口写入）
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    submitted_at   TEXT,
    graded_at      TEXT
);

-- U14 试题及来源。answer 不可在未交卷时下发前端。
CREATE TABLE IF NOT EXISTS self_test_items (
    item_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id            INTEGER NOT NULL REFERENCES self_tests(test_id) ON DELETE CASCADE,
    seq                INTEGER NOT NULL DEFAULT 0,
    knowledge_name     TEXT NOT NULL DEFAULT '',
    question_type      TEXT NOT NULL DEFAULT 'single'
                       CHECK (question_type IN ('single', 'judge', 'short')),
    stem               TEXT NOT NULL,
    options_json       TEXT NOT NULL DEFAULT '[]',
    answer             TEXT NOT NULL DEFAULT '',
    analysis           TEXT NOT NULL DEFAULT '',
    evidence_chunk_key TEXT NOT NULL DEFAULT '',
    evidence_page      INTEGER,
    user_answer        TEXT,
    is_correct         INTEGER,
    score              REAL NOT NULL DEFAULT 0,
    answered_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_sti_test ON self_test_items(test_id);

-- U13 错题本。重复答错同一 source_id 时由服务层递增 wrong_count。
CREATE TABLE IF NOT EXISTS wrong_questions (
    wrong_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    knowledge_name     TEXT NOT NULL,
    source_type        TEXT NOT NULL DEFAULT 'self_test'
                       CHECK (source_type IN ('self_test', 'manual')),
    source_id          INTEGER NOT NULL,
    question_stem      TEXT NOT NULL DEFAULT '',
    correct_answer     TEXT NOT NULL DEFAULT '',
    analysis           TEXT NOT NULL DEFAULT '',
    evidence_chunk_key TEXT NOT NULL DEFAULT '',
    evidence_page      INTEGER,
    wrong_count        INTEGER NOT NULL DEFAULT 1,
    correct_streak     INTEGER NOT NULL DEFAULT 0,
    mastered           INTEGER NOT NULL DEFAULT 0,
    last_wrong_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, source_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_wq_user_kp ON wrong_questions(user_id, knowledge_name);

-- U15 图形导图邻接表，节点由导图后端负责生成和更新。
CREATE TABLE IF NOT EXISTS mindmap_nodes (
    node_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    user_id            INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    parent_id          INTEGER REFERENCES mindmap_nodes(node_id) ON DELETE CASCADE,
    name               TEXT NOT NULL,
    level              INTEGER NOT NULL DEFAULT 1,
    summary            TEXT NOT NULL DEFAULT '',
    evidence_chunk_key TEXT NOT NULL DEFAULT '',
    evidence_page      INTEGER,
    seq                INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mn_session ON mindmap_nodes(session_id, parent_id, seq);
