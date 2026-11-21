-- 大学生课程课件笔记整理与知识梳理 Agent —— 数据库结构
-- 对应《数据库（知识库）相关工作.docx》第三部分（业务库）+ 第一部分（领域知识库）
--
-- 设计要点：
--   1. 业务库与领域知识库分两个 SQLite 文件（business.db / kb.db），对应 SRS 3.4「物理或逻辑分离」
--   2. 课程文档的正文统一放 chunks 表，并由 ft_chunks 建立 FTS5 全文索引（中文按 2-gram 处理）
--   3. 可选功能（例题/公式/出处索引/版本）的表也一并建好，未启用时不影响主线
--   4. 时间统一用 TEXT + CURRENT_TIMESTAMP（UTC），显示时区由前端处理

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============================================================
-- 一、业务库（用户使用系统时产生的数据）
-- ============================================================

-- DB-01 用户
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    nickname      TEXT    NOT NULL DEFAULT '',
    email         TEXT,
    avatar        TEXT,
    role          TEXT    NOT NULL DEFAULT 'student'
                  CHECK (role IN ('student', 'admin')),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- DB-02 课程材料（一次上传 = 一条）
CREATE TABLE IF NOT EXISTS documents (
    doc_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    course_name   TEXT    NOT NULL DEFAULT '',
    source_file   TEXT    NOT NULL,                -- 用户上传时的原始文件名（展示与出处用）
    display_name  TEXT    NOT NULL DEFAULT '',     -- 同 source_file，保留字段便于后续改名
    stored_path   TEXT    NOT NULL,                -- 落盘路径（文件名是内容哈希，不外露）
    -- file_type 由解析器按文件头判定后写入（pdf/pptx/docx/txt/md/html/csv/epub/image）。
    -- 刻意不加 CHECK 约束：支持的格式会随需求扩展，写死枚举会让新增格式无法入库。
    file_type     TEXT    NOT NULL,
    file_size     INTEGER NOT NULL DEFAULT 0,
    page_count    INTEGER NOT NULL DEFAULT 0,
    text_chars    INTEGER NOT NULL DEFAULT 0,
    is_public     INTEGER NOT NULL DEFAULT 0,      -- 1 = 管理员维护的公共资料
    parse_status  TEXT    NOT NULL DEFAULT 'pending'
                  CHECK (parse_status IN ('pending', 'success', 'partial', 'failed')),
    parse_message TEXT,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_documents_user   ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_course ON documents(course_name);

-- 文档正文分块（解析产物，Agent 一切结论的证据来源）
-- chunk_key 形如 d12-p7-c3：文档 12 / 第 7 页（PPT 用幻灯序号）/ 该页第 3 块
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_key     TEXT    NOT NULL UNIQUE,
    doc_id        INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,               -- 全文顺序
    chapter_title TEXT    NOT NULL DEFAULT '',
    section_title TEXT    NOT NULL DEFAULT '',
    page_num      INTEGER,                        -- PDF 页码
    slide_index   INTEGER,                        -- PPT 幻灯片序号
    char_start    INTEGER NOT NULL DEFAULT 0,     -- 在整篇文本中的字符偏移
    char_end      INTEGER NOT NULL DEFAULT 0,
    text          TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, seq);

-- 全文索引：text_bigram 存 2-gram 串（中文检索用），text_raw 服务于英文/数字原样检索
CREATE VIRTUAL TABLE IF NOT EXISTS ft_chunks USING fts5(
    chunk_key  UNINDEXED,
    doc_id     UNINDEXED,
    text_bigram,
    text_raw,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- DB-03 整理任务
CREATE TABLE IF NOT EXISTS sessions (
    session_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    course_name   TEXT    NOT NULL DEFAULT '',
    source_file   TEXT    NOT NULL DEFAULT '',
    doc_ids       TEXT    NOT NULL DEFAULT '[]',   -- JSON 数组：[12, 15]
    task_type     TEXT    NOT NULL DEFAULT 'note'
                  CHECK (task_type IN ('note', 'example', 'exam_scope')),
    exam_scope    TEXT,                            -- OP-05 考试范围原文
    status        TEXT    NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'running', 'success', 'partial', 'failed')),
    progress      INTEGER NOT NULL DEFAULT 0,      -- 0-100，前端进度条
    stage_message TEXT    NOT NULL DEFAULT '',
    error_message TEXT,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, created_at DESC);

-- DB-03 整理产物：结构化笔记 / 重点清单 / 文本思维导图 用 content_type 区分
CREATE TABLE IF NOT EXISTS notes (
    note_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id    INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    course_name   TEXT    NOT NULL DEFAULT '',
    chapter_title TEXT    NOT NULL DEFAULT '',
    content_type  TEXT    NOT NULL DEFAULT 'note'
                  CHECK (content_type IN ('note', 'key_points', 'mindmap')),
    content       TEXT    NOT NULL,
    quality_json  TEXT,                            -- OP-06 权重自评结果
    dropped_items INTEGER NOT NULL DEFAULT 0,      -- 被证据校验丢弃的条目数（答辩亮点）
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notes_session ON notes(session_id);
CREATE INDEX IF NOT EXISTS idx_notes_user    ON notes(user_id, created_at DESC);

-- 知识点条目 + 证据绑定（结构化笔记的原始数据；OP-03 出处展示的数据源）
CREATE TABLE IF NOT EXISTS note_items (
    item_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id         INTEGER NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    definition      TEXT    NOT NULL DEFAULT '',
    key_points_json TEXT    NOT NULL DEFAULT '[]',
    formula_latex   TEXT,
    importance      INTEGER NOT NULL DEFAULT 3,    -- 重要度 1-5
    evidence_json   TEXT    NOT NULL DEFAULT '[]', -- [{chunk_key,source_file,page_num,slide_index,quote}]
    verified        INTEGER NOT NULL DEFAULT 0,    -- 证据校验是否通过
    user_edited     INTEGER NOT NULL DEFAULT 0,    -- OP-04 合并时受保护
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_note_items_note ON note_items(note_id, sort_order);

-- DB-07 / OP-04 笔记版本（合并快照 + 变更摘要）
CREATE TABLE IF NOT EXISTS note_versions (
    version_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id          INTEGER NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    version_no       INTEGER NOT NULL,
    content_snapshot TEXT    NOT NULL,
    change_summary   TEXT    NOT NULL DEFAULT '',
    user_edited      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_note_versions ON note_versions(note_id, version_no);

-- DB-04 对话（问答历史：用于演示、错误分析与评测）
CREATE TABLE IF NOT EXISTS chats (
    chat_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    course_name   TEXT    NOT NULL DEFAULT '',
    doc_id        INTEGER REFERENCES documents(doc_id) ON DELETE SET NULL,
    role          TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
    content       TEXT    NOT NULL,
    evidence_json TEXT    NOT NULL DEFAULT '[]',
    insufficient  INTEGER NOT NULL DEFAULT 0,      -- 1 = 明确回答"材料未涉及"
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id, created_at DESC);

-- OP-01 例题记录
CREATE TABLE IF NOT EXISTS example_records (
    record_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id     INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    knowledge_name TEXT    NOT NULL DEFAULT '',
    difficulty     TEXT    NOT NULL DEFAULT '基础'
                   CHECK (difficulty IN ('基础', '进阶', '挑战')),
    question       TEXT    NOT NULL,
    answer         TEXT    NOT NULL DEFAULT '',
    analysis       TEXT    NOT NULL DEFAULT '',
    source         TEXT    NOT NULL DEFAULT 'Agent生成'
                   CHECK (source IN ('检索例题库', 'Agent生成')),
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_example_records_session ON example_records(session_id);

-- OP-02 公式转换记录（本期不实施，保留表结构便于后续启用）
CREATE TABLE IF NOT EXISTS formula_records (
    record_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    image_url  TEXT    NOT NULL,
    latex_code TEXT    NOT NULL DEFAULT '',
    status     TEXT    NOT NULL DEFAULT '成功'
               CHECK (status IN ('成功', '待人工校验', '失败')),
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- 学习闭环（U13 错题本 / U14 自测 / U15 图形导图）
-- ============================================================
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

-- ============================================================
-- 二、领域知识库（管理员维护的公共事实源，只读）
-- ============================================================

CREATE TABLE IF NOT EXISTS knowledge_points (
    knowledge_id  TEXT PRIMARY KEY,                -- 如 K001
    course_id     TEXT NOT NULL DEFAULT '',
    chapter_id    TEXT NOT NULL DEFAULT '',
    name          TEXT NOT NULL,
    definition    TEXT NOT NULL DEFAULT '',
    key_points    TEXT NOT NULL DEFAULT '',
    formula       TEXT,
    prerequisite  TEXT,
    doc_id        INTEGER,                         -- 关联上传的公共课件
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kp_course ON knowledge_points(course_id, chapter_id);

CREATE TABLE IF NOT EXISTS knowledge_relations (
    relation_id       TEXT PRIMARY KEY,
    from_knowledge_id TEXT NOT NULL REFERENCES knowledge_points(knowledge_id) ON DELETE CASCADE,
    to_knowledge_id   TEXT NOT NULL REFERENCES knowledge_points(knowledge_id) ON DELETE CASCADE,
    relation_type     TEXT NOT NULL
                      CHECK (relation_type IN ('前置', '后置', '并列', '包含', '应用')),
    description       TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS example_problems (
    problem_id   TEXT PRIMARY KEY,
    knowledge_id TEXT REFERENCES knowledge_points(knowledge_id) ON DELETE SET NULL,
    difficulty   TEXT NOT NULL DEFAULT '基础'
                 CHECK (difficulty IN ('基础', '进阶', '挑战')),
    question     TEXT NOT NULL,
    answer       TEXT NOT NULL DEFAULT '',
    analysis     TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '教材'
                 CHECK (source IN ('教材', '试卷', '自编', 'Agent生成')),
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_example_problems_kp ON example_problems(knowledge_id, difficulty);

CREATE TABLE IF NOT EXISTS latex_rules (
    rule_id       TEXT PRIMARY KEY,
    symbol_name   TEXT NOT NULL,
    symbol        TEXT NOT NULL DEFAULT '',
    latex_code    TEXT NOT NULL,
    usage_example TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '运算符'
                  CHECK (category IN ('运算符', '希腊字母', '积分', '矩阵', '函数', '表达式')),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_index (
    index_id     TEXT PRIMARY KEY,
    knowledge_id TEXT REFERENCES knowledge_points(knowledge_id) ON DELETE CASCADE,
    chunk_key    TEXT NOT NULL,
    chapter_title TEXT NOT NULL DEFAULT '',
    page_num     INTEGER,
    quote        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_source_index_kp ON source_index(knowledge_id);

-- 说明：管理员账号由 scripts/init_db.py 用 app/core/security.py 生成口令哈希后写入，
-- 不在此处硬编码初始口令，避免占位符被直接当成可用口令提交上线。
