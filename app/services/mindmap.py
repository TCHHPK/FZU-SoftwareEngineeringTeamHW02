"""U15 图形化思维导图的数据服务。

职责：把「笔记的章节 + 知识点」变成一棵树写进 mindmap_nodes，再按树读出来。
前端（MindMapGraph.vue）既能吃嵌套树，也能吃扁平邻接表，这里两种都给。

设计取舍：
    1. 树结构只从已有笔记派生，不调用模型——导图不该再花钱，也不该产生新内容；
    2. 每次 build 都是「先删后插」的幂等操作，重复点「重新生成」不会堆出重复节点；
    3. 每个知识点节点尽量带上 evidence_page / evidence_chunk_key，
       前端点节点就能跳回原文，这是本产品的一条底线（出处可追溯）。
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from app.agents.quiz import QuizUnavailable
from app.db.conn import transaction


def _own_session(conn: sqlite3.Connection, session_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    # 越权与不存在都返回 LookupError，路由层统一转 404，不暴露「存在但不属于你」
    if row is None or int(row["user_id"]) != int(user_id):
        raise LookupError("整理任务不存在")
    return row


def _nest(rows: list[sqlite3.Row]) -> dict | None:
    """邻接表 → 嵌套树。返回根节点（level 最小的第一个节点）。"""
    nodes: dict[int, dict] = {}
    for row in rows:
        nodes[int(row["node_id"])] = {
            "node_id": int(row["node_id"]),
            "name": row["name"],
            "level": int(row["level"] or 1),
            "summary": row["summary"] or "",
            "evidence_page": row["evidence_page"],
            "evidence_chunk_key": row["evidence_chunk_key"] or "",
            "children": [],
        }
    root: dict | None = None
    for row in rows:
        node = nodes[int(row["node_id"])]
        parent_id = row["parent_id"]
        if parent_id is None or int(parent_id) not in nodes:
            if root is None:
                root = node
        else:
            nodes[int(parent_id)]["children"].append(node)
    return root


def read_tree(conn: sqlite3.Connection, session_id: int, user_id: int) -> dict:
    """读取已生成的导图。没有数据时 built=False，前端据此提示「还没生成」。"""
    session = _own_session(conn, session_id, user_id)
    rows = conn.execute(
        """SELECT * FROM mindmap_nodes
            WHERE session_id = ? ORDER BY level ASC, seq ASC, node_id ASC""",
        (int(session_id),),
    ).fetchall()
    if not rows:
        return {
            "built": False,
            "course_name": session["course_name"] or "",
            "tree": None,
            "nodes": [],
        }
    return {
        "built": True,
        "course_name": session["course_name"] or "",
        "tree": _nest(rows),
        "nodes": [dict(row) for row in rows],
    }


def build_tree(conn: sqlite3.Connection, session_id: int, user_id: int) -> dict:
    """由笔记章节与知识点生成导图节点，然后返回整棵树。"""
    session = _own_session(conn, session_id, user_id)

    notes = conn.execute(
        """SELECT note_id, chapter_title FROM notes
            WHERE session_id = ? AND content_type = 'note'
            ORDER BY note_id ASC""",
        (int(session_id),),
    ).fetchall()
    if not notes:
        raise QuizUnavailable("该任务还没有结构化笔记，无法生成导图")

    root_name = (session["course_name"] or "").strip() or "课程笔记"

    with transaction(conn):
        conn.execute("DELETE FROM mindmap_nodes WHERE session_id = ?", (int(session_id),))

        cursor = conn.execute(
            """INSERT INTO mindmap_nodes
                 (session_id, user_id, parent_id, name, level, summary, seq)
               VALUES (?, ?, NULL, ?, 1, ?, 0)""",
            (int(session_id), int(user_id), root_name, "课程知识结构"),
        )
        root_id = int(cursor.lastrowid)

        for chapter_seq, note in enumerate(notes):
            chapter = _short_name(note["chapter_title"]) or "未标注章节"
            cursor = conn.execute(
                """INSERT INTO mindmap_nodes
                     (session_id, user_id, parent_id, name, level, summary, seq)
                   VALUES (?, ?, ?, ?, 2, '', ?)""",
                (int(session_id), int(user_id), root_id, chapter, chapter_seq),
            )
            chapter_id = int(cursor.lastrowid)

            items = conn.execute(
                """SELECT name, definition, evidence_json FROM note_items
                    WHERE note_id = ? ORDER BY sort_order ASC, item_id ASC""",
                (int(note["note_id"]),),
            ).fetchall()
            for item_seq, item in enumerate(items):
                page, chunk_key = _first_evidence(item["evidence_json"])
                conn.execute(
                    """INSERT INTO mindmap_nodes
                         (session_id, user_id, parent_id, name, level, summary,
                          evidence_chunk_key, evidence_page, seq)
                       VALUES (?, ?, ?, ?, 3, ?, ?, ?, ?)""",
                    (int(session_id), int(user_id), chapter_id,
                     _short_name(item["name"]) or "知识点",
                     (item["definition"] or "")[:200], chunk_key, page, item_seq),
                )

    return read_tree(conn, session_id, user_id)


def _short_name(raw: Any) -> str:
    """把章节名/知识点名压成适合显示在节点卡片上的短标题。

    为什么需要：占位实现（无模型密钥）下，章节名取自分块首行，
    可能是「3.1 等价类划分｜3.1 等价类划分等价类划分把输入域划分…」这种整句，
    直接画在图上会撑爆卡片、也看不出层级。规则与自测出题处保持一致：
        1. 遇到「｜」「|」「。」「换行」只取前段；
        2. 截掉「本章/本讲/本节」之后的说明性文字；
        3. 超过 20 字截断加省略号。
    """
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return ""
    text = re.split(r"[｜|。\n]", text)[0].strip()
    text = re.sub(r"(本章|本讲|本节)\s*.*$", "", text).strip()
    if not text:
        return ""
    return text if len(text) <= 20 else text[:20].rstrip() + "…"


def _first_evidence(raw: Any) -> tuple[int | None, str]:
    """从 evidence_json 里取第一条的页码与 chunk_key，取不到就返回空值。"""
    try:
        parsed = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return None, ""
    if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], dict):
        return None, ""
    first = parsed[0]
    page = first.get("page_num")
    try:
        page = int(page) if page is not None else None
    except (TypeError, ValueError):
        page = None
    return page, str(first.get("chunk_key") or "")


__all__ = ["build_tree", "read_tree"]
