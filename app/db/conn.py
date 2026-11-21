"""SQLite 连接管理。

两个数据库文件，对应 SRS 3.4「业务数据与领域知识物理或逻辑分离」：
    storage/business.db  用户、文档、任务、笔记、对话……
    storage/kb.db        公共领域知识库（管理员维护，Agent 只读）
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR / "storage"))

BUSINESS_DB = Path(os.getenv("BUSINESS_DB", STORAGE_DIR / "business.db"))
KB_DB = Path(os.getenv("KB_DB", STORAGE_DIR / "kb.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def business_db() -> Iterator[sqlite3.Connection]:
    conn = _connect(BUSINESS_DB)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def kb_db() -> Iterator[sqlite3.Connection]:
    conn = _connect(KB_DB)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_databases(*, reset: bool = False) -> dict[str, str]:
    """建库建表。reset=True 时删除已有文件（仅开发期使用）。

    返回 {"business": 路径, "kb": 路径}。
    """
    if reset:
        for path in (BUSINESS_DB, KB_DB):
            for suffix in ("", "-wal", "-shm"):
                f = Path(str(path) + suffix)
                if f.exists():
                    f.unlink()

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    business_section, _, kb_section = schema.partition("-- 二、领域知识库")

    with business_db() as conn:
        conn.executescript(business_section)
        _migrate_business(conn)
        _run_migrations(conn)
    with kb_db() as conn:
        conn.executescript("-- 二、领域知识库" + kb_section)

    return {"business": str(BUSINESS_DB), "kb": str(KB_DB)}


# 增量迁移：字段以 schema.sql 为准，这里保证已存在的库也能补上新字段
_BUSINESS_MIGRATIONS: list[tuple[str, str, str]] = [
    ("documents", "display_name", "TEXT NOT NULL DEFAULT ''"),
    # 自测表由 migrations/002 创建；老库升级时补上「出题失败原因」字段，
    # 否则自测接口在旧库上会报 no such column: error_message
    ("self_tests", "error_message", "TEXT NOT NULL DEFAULT ''"),
]


def _migrate_business(conn: sqlite3.Connection) -> None:
    for table, column, definition in _BUSINESS_MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            # 表还没建（会在后面的 _run_migrations 里创建），跳过，避免 ALTER 报错
            continue
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    # 历史数据回填：display_name 为空时用 source_file 兜底
    conn.execute("UPDATE documents SET display_name = source_file WHERE display_name = ''")


def _run_migrations(conn: sqlite3.Connection) -> None:
    """执行 app/db/migrations/ 下的增量迁移脚本（按文件名排序）。

    迁移文件全部使用 IF NOT EXISTS / IF NOT EXISTS 风格，幂等可重入。
    新增表（self_tests / wrong_questions / mindmap_nodes 等）放在这里，
    避免每次都改主 schema.sql；老库升级时也能自动补表。
    """
    if not MIGRATIONS_DIR.exists():
        return
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        if sql.strip():
            conn.executescript(sql)
