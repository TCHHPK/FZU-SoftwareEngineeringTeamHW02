"""业务数据读写：文档、任务、产物、对话。

放在一处集中管理 SQL，路由层只做参数校验与权限判断，不直接写 SQL。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.schemas.agent_io import Evidence, NoteResult, QualityScore


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


# --------------------------------------------------------------------------
# 用户
# --------------------------------------------------------------------------
def get_user_by_username(conn: sqlite3.Connection, username: str) -> dict | None:
    return _row(conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())


def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    return _row(conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone())


def create_user(conn: sqlite3.Connection, username: str, password_hash: str,
                nickname: str = "", role: str = "student") -> int:
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, nickname, role) VALUES (?, ?, ?, ?)",
        (username, password_hash, nickname or username, role))
    return int(cur.lastrowid)


# --------------------------------------------------------------------------
# 文档
# --------------------------------------------------------------------------
def list_documents(conn: sqlite3.Connection, user_id: int, *,
                   include_public: bool = True) -> list[dict]:
    """用户可见的材料：自己的私有材料 + 管理员维护的公共资料。"""
    if include_public:
        # 用命名参数，避免「两个占位符只传一个值」这类错误再次发生
        sql = ("SELECT * FROM documents WHERE user_id = :uid OR is_public = 1"
               " ORDER BY created_at DESC, doc_id DESC")
        return [dict(r) for r in conn.execute(sql, {"uid": user_id}).fetchall()]

    sql = ("SELECT * FROM documents WHERE user_id = :uid"
           " ORDER BY created_at DESC, doc_id DESC")
    return [dict(r) for r in conn.execute(sql, {"uid": user_id}).fetchall()]


def get_document(conn: sqlite3.Connection, doc_id: int) -> dict | None:
    return _row(conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone())


def list_documents_by_ids(conn: sqlite3.Connection, doc_ids: list[int]) -> list[dict]:
    if not doc_ids:
        return []
    placeholders = ",".join(f":d{i}" for i in range(len(doc_ids)))
    params = {f"d{i}": int(v) for i, v in enumerate(doc_ids)}
    rows = conn.execute(f"SELECT * FROM documents WHERE doc_id IN ({placeholders})",
                        params).fetchall()
    return [dict(r) for r in rows]


def user_can_access_doc(conn: sqlite3.Connection, doc_id: int, user_id: int) -> bool:
    """文档访问权：自己的文档，或管理员维护的公共资料。"""
    row = conn.execute(
        "SELECT 1 FROM documents WHERE doc_id = ? AND (user_id = ? OR is_public = 1)",
        (doc_id, user_id)).fetchone()
    return row is not None


def count_chunks(conn: sqlite3.Connection, doc_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM chunks WHERE doc_id = ?",
                            (doc_id,)).fetchone()["c"])


# --------------------------------------------------------------------------
# 任务
# --------------------------------------------------------------------------
def create_session(conn: sqlite3.Connection, *, user_id: int, course_name: str,
                   source_file: str, doc_ids: list[int], task_type: str = "note",
                   exam_scope: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO sessions (user_id, course_name, source_file, doc_ids, task_type,
                                 exam_scope, status, progress, stage_message)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, '任务已创建，等待处理')""",
        (user_id, course_name, source_file, json.dumps(doc_ids), task_type, exam_scope))
    return int(cur.lastrowid)


def get_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    row = _row(conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone())
    if row:
        row["doc_ids"] = _loads(row.get("doc_ids"), [])
    return row


def list_sessions(conn: sqlite3.Connection, user_id: int, *, limit: int = 50,
                  offset: int = 0) -> list[dict]:
    rows = conn.execute(
        """SELECT s.*, (SELECT COUNT(*) FROM notes n WHERE n.session_id = s.session_id) AS note_count
           FROM sessions s WHERE s.user_id = ?
           ORDER BY s.created_at DESC, s.session_id DESC LIMIT ? OFFSET ?""",
        (user_id, limit, offset)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["doc_ids"] = _loads(d.get("doc_ids"), [])
        out.append(d)
    return out


def update_session(conn: sqlite3.Connection, session_id: int, **fields: Any) -> None:
    allowed = {"status", "progress", "stage_message", "error_message", "finished_at", "course_name"}
    sets, params = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"不允许更新 sessions.{key}")
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return
    if fields.get("status") in {"success", "partial", "failed"}:
        sets.append("finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP)")
    params.append(session_id)
    conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE session_id = ?", params)


# --------------------------------------------------------------------------
# 产物
# --------------------------------------------------------------------------
def save_note(conn: sqlite3.Connection, *, user_id: int, session_id: int, course_name: str,
              content_type: str, content: str, chapter_title: str = "",
              quality: QualityScore | None = None, dropped_items: int = 0) -> int:
    cur = conn.execute(
        """INSERT INTO notes (user_id, session_id, course_name, chapter_title, content_type,
                              content, quality_json, dropped_items)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, session_id, course_name, chapter_title, content_type, content,
         quality.model_dump_json() if quality else None, dropped_items))
    return int(cur.lastrowid)


def save_note_items(conn: sqlite3.Connection, note_id: int, items: list[dict]) -> int:
    if not items:
        return 0
    conn.executemany(
        """INSERT INTO note_items (note_id, name, definition, key_points_json, formula_latex,
                                   importance, evidence_json, verified, sort_order)
           VALUES (:note_id, :name, :definition, :key_points_json, :formula_latex,
                   :importance, :evidence_json, :verified, :sort_order)""",
        [{
            "note_id": note_id,
            "name": it.get("name", ""),
            "definition": it.get("definition", ""),
            "key_points_json": json.dumps(it.get("key_points", []), ensure_ascii=False),
            "formula_latex": it.get("formula_latex"),
            "importance": int(it.get("importance", 3)),
            "evidence_json": json.dumps(it.get("evidence", []), ensure_ascii=False),
            "verified": 1 if it.get("verified") else 0,
            "sort_order": idx,
        } for idx, it in enumerate(items)])
    return len(items)


def list_notes(conn: sqlite3.Connection, session_id: int, *,
               content_type: str | None = None) -> list[dict]:
    sql = "SELECT * FROM notes WHERE session_id = ?"
    params: list = [session_id]
    if content_type:
        sql += " AND content_type = ?"
        params.append(content_type)
    sql += " ORDER BY note_id"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_note(conn: sqlite3.Connection, note_id: int) -> dict | None:
    return _row(conn.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone())


def list_note_items(conn: sqlite3.Connection, note_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM note_items WHERE note_id = ? ORDER BY sort_order, item_id",
        (note_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["key_points"] = _loads(d.pop("key_points_json", None), [])
        d["evidence"] = _loads(d.pop("evidence_json", None), [])
        d["verified"] = bool(d["verified"])
        d["user_edited"] = bool(d["user_edited"])
        out.append(d)
    return out


def count_note_items(conn: sqlite3.Connection, note_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM note_items WHERE note_id = ?",
                            (note_id,)).fetchone()["c"])


# --------------------------------------------------------------------------
# 对话
# --------------------------------------------------------------------------
def save_chat(conn: sqlite3.Connection, *, user_id: int, role: str, content: str,
              course_name: str = "", doc_id: int | None = None,
              evidence: list[Evidence] | None = None, insufficient: bool = False) -> int:
    cur = conn.execute(
        """INSERT INTO chats (user_id, course_name, doc_id, role, content, evidence_json, insufficient)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, course_name, doc_id, role, content,
         json.dumps([e.model_dump() for e in (evidence or [])], ensure_ascii=False),
         1 if insufficient else 0))
    return int(cur.lastrowid)


def list_chats(conn: sqlite3.Connection, user_id: int, *, course_name: str | None = None,
               limit: int = 30) -> list[dict]:
    sql = "SELECT * FROM chats WHERE user_id = :uid"
    params: dict = {"uid": user_id, "limit": limit}
    if course_name:
        sql += " AND course_name = :course"
        params["course"] = course_name
    sql += " ORDER BY chat_id DESC LIMIT :limit"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in reversed(rows):
        d = dict(r)
        d["evidence"] = _loads(d.pop("evidence_json", None), [])
        d["insufficient"] = bool(d["insufficient"])
        out.append(d)
    return out


def list_courses(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """用户可见的课程清单：用于前端上传页与问答页的课程选择。"""
    rows = conn.execute(
        """SELECT course_name, COUNT(*) AS doc_count, MAX(created_at) AS last_upload
           FROM documents WHERE (user_id = :uid OR is_public = 1) AND course_name <> ''
           GROUP BY course_name ORDER BY last_upload DESC""",
        {"uid": user_id}).fetchall()
    return [dict(r) for r in rows]


def session_result(conn: sqlite3.Connection, session_id: int) -> NoteResult | None:
    """把一次任务的全部产物组装成 NoteResult（离线回看、导出、评测都用它）。"""
    sess = get_session(conn, session_id)
    if not sess:
        return None
    notes = list_notes(conn, session_id)
    note = next((n for n in notes if n["content_type"] == "note"), None)
    kp = next((n for n in notes if n["content_type"] == "key_points"), None)
    mm = next((n for n in notes if n["content_type"] == "mindmap"), None)

    quality = None
    if note and note.get("quality_json"):
        try:
            quality = QualityScore.model_validate_json(note["quality_json"])
        except Exception:  # noqa: BLE001 - 历史脏数据不应让回看失败
            quality = None

    outline: list[dict] = []
    if note:
        items = list_note_items(conn, note["note_id"])
        outline = [{
            "title": note["chapter_title"] or sess["course_name"],
            "level": 1,
            "summary": "",
            "items": items,
        }]
    return NoteResult(
        course_name=sess["course_name"],
        outline=outline,
        key_points=_loads(kp["content"], []) if kp and kp["content"].strip().startswith("[") else
        ([line for line in (kp["content"].splitlines() if kp else []) if line.strip()]),
        mindmap_text=mm["content"] if mm else "",
        quality=quality,
        dropped_items=note["dropped_items"] if note else 0,
    )
