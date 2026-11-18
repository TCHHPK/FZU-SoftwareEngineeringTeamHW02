"""入库：把解析结果写进 documents / chunks / ft_chunks。

分成「纯解析（parse.py）」与「落库（ingest.py）」两层，
解析可以脱离数据库测试，入库可以脱离真实大文件测试。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.services.parse import Chunk, ParseError, ParsedDocument, build_chunks, parse_file
from app.services.query import index_chunks


def ensure_user(conn: sqlite3.Connection, username: str = "tester", *,
                role: str = "student", nickname: str = "") -> int:
    """开发/测试用的用户获取，正式注册流程走 app/api/routes_auth.py。"""
    row = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
    if row:
        return int(row["user_id"])
    from app.core.security import hash_password

    cur = conn.execute(
        "INSERT INTO users (username, password_hash, nickname, role) VALUES (?, ?, ?, ?)",
        (username, hash_password(f"{username}-dev-only"), nickname or username, role),
    )
    return int(cur.lastrowid)


def create_document(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    course_name: str,
    source_file: str,
    stored_path: str,
    file_type: str,
    display_name: str = "",
    page_count: int = 0,
    text_chars: int = 0,
    file_size: int = 0,
    is_public: bool = False,
    parse_status: str = "pending",
    parse_message: str = "",
) -> int:
    cur = conn.execute(
        """INSERT INTO documents (user_id, course_name, source_file, display_name, stored_path,
                                  file_type, file_size, page_count, text_chars, is_public,
                                  parse_status, parse_message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, course_name, source_file, display_name or source_file, stored_path,
         file_type, file_size, page_count, text_chars, 1 if is_public else 0,
         parse_status, parse_message),
    )
    return int(cur.lastrowid)


def save_chunks(conn: sqlite3.Connection, chunks: list[Chunk]) -> int:
    """写入 chunks 并同步全文索引。返回写入条数。"""
    if not chunks:
        return 0
    conn.executemany(
        """INSERT INTO chunks (chunk_key, doc_id, seq, chapter_title, section_title,
                               page_num, slide_index, char_start, char_end, text)
           VALUES (:chunk_key, :doc_id, :seq, :chapter_title, :section_title,
                   :page_num, :slide_index, :char_start, :char_end, :text)""",
        [c.__dict__ for c in chunks],
    )
    index_chunks(conn, [{"chunk_key": c.chunk_key, "doc_id": c.doc_id, "text": c.text}
                        for c in chunks])
    return len(chunks)


def ingest_document(
    conn: sqlite3.Connection,
    file_path: str | Path,
    *,
    user_id: int,
    course_name: str,
    stored_path: str | None = None,
    display_name: str = "",
    is_public: bool = False,
) -> dict:
    """完整入库流程：解析 → 建文档记录 → 切块 → 建索引。

    返回 {"doc_id", "chunks", "page_count", "warnings", "parse_status"}。
    解析失败（ParseError）由调用方捕获后自行写入 failed 状态。

    parse_status 的判定（对应 FR-02「部分页面未成功解析时应提示处理范围」）：
        success —— 全部页面正常
        partial —— 有页面失败、或存在乱码/图片页等告警
    """
    path = Path(file_path)

    try:
        parsed: ParsedDocument = parse_file(path, course_name=course_name)
    except ParseError as exc:
        doc_id = create_document(
            conn, user_id=user_id, course_name=course_name, source_file=display_name or path.name,
            stored_path=stored_path or str(path), file_type=path.suffix.lstrip(".").lower(),
            file_size=path.stat().st_size if path.exists() else 0,
            is_public=is_public, parse_status="failed", parse_message=str(exc),
        )
        return {"doc_id": doc_id, "chunks": 0, "page_count": 0,
                "warnings": [str(exc)], "parse_status": "failed", "message": str(exc)}

    failed_pages = [p for p in parsed.pages if p.failed]
    status = "partial" if (failed_pages or parsed.warnings) else "success"

    doc_id = create_document(
        conn, user_id=user_id, course_name=course_name, source_file=display_name or path.name,
        stored_path=stored_path or str(path), file_type=parsed.file_type,
        page_count=parsed.page_count, text_chars=parsed.text_chars,
        file_size=path.stat().st_size, is_public=is_public,
        parse_status=status, parse_message="；".join(parsed.warnings[:5]),
    )

    chunks = build_chunks(parsed, doc_id)
    saved = save_chunks(conn, chunks)

    return {
        "doc_id": doc_id,
        "chunks": saved,
        "page_count": parsed.page_count,
        "warnings": parsed.warnings,
        "parse_status": status,
        "chapters": sorted({c.chapter_title for c in chunks if c.chapter_title}),
    }


def document_summary(conn: sqlite3.Connection, doc_id: int) -> dict:
    """给前端和管理端看的文档概况。"""
    doc = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if not doc:
        return {}
    stats = conn.execute(
        """SELECT COUNT(*) AS chunks, COUNT(DISTINCT chapter_title) AS chapters,
                  MIN(page_num) AS first_page, MAX(page_num) AS last_page
           FROM chunks WHERE doc_id = ?""", (doc_id,)).fetchone()
    return {
        "doc_id": doc_id,
        "course_name": doc["course_name"],
        "source_file": doc["source_file"],
        "file_type": doc["file_type"],
        "page_count": doc["page_count"],
        "parse_status": doc["parse_status"],
        "parse_message": doc["parse_message"],
        "chunk_count": stats["chunks"],
        "chapter_count": stats["chapters"],
        "doc_ids": json.dumps([doc_id]),
    }
