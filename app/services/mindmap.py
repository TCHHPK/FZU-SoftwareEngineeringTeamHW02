"""由已整理知识点构建课程、章节、知识点三层树；重建原子替换。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.agents.quiz import QuizUnavailable, session_material
from app.db.conn import transaction


def read_tree(conn: sqlite3.Connection, session_id: int, user_id: int) -> dict:
    session, _ = session_material(conn, session_id, user_id)
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mindmap_nodes'").fetchone()
    rows = conn.execute("SELECT * FROM mindmap_nodes WHERE session_id=? AND user_id=? ORDER BY seq,node_id",
                        (session_id, user_id)).fetchall() if exists else []
    nodes = {row["node_id"]: {**dict(row), "children": []} for row in rows}
    roots = []
    for node in nodes.values():
        if node["parent_id"] is None:
            roots.append(node)
        elif node["parent_id"] in nodes:
            nodes[node["parent_id"]]["children"].append(node)
    return {"session_id": session_id, "course_name": session["course_name"],
            "node_count": len(nodes), "tree": roots[0] if roots else None}


def build_tree(conn: sqlite3.Connection, session_id: int, user_id: int) -> dict:
    session, material = session_material(conn, session_id, user_id)
    if not material:
        raise QuizUnavailable("没有带真实出处的知识点，无法生成导图")
    # 独立交付兼容旧代码包；与团队 002 中相同 DDL 可重复执行。
    ddl = (Path(__file__).parent / "mindmap_schema.sql").read_text(encoding="utf-8")
    with transaction(conn):
        # execute 而非 executescript，避免 SQLite 隐式提交破坏原子性。
        for statement in ddl.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute("DELETE FROM mindmap_nodes WHERE session_id=? AND user_id=?", (session_id, user_id))

        def insert(parent_id, name, level, seq, summary="", key="", page=None):
            cursor = conn.execute("""INSERT INTO mindmap_nodes
                (session_id,user_id,parent_id,name,level,summary,evidence_chunk_key,evidence_page,seq)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (session_id, user_id, parent_id, name, level, summary, key, page, seq))
            return cursor.lastrowid

        root = insert(None, session["course_name"] or "课程笔记", 1, 0)
        chapters = {}
        for seq, fact in enumerate(material):
            title = fact["chapter_title"] or "未命名章节"
            if title not in chapters:
                chapters[title] = insert(root, title, 2, len(chapters))
            insert(chapters[title], fact["knowledge_name"], 3, seq,
                   fact["summary"], fact["evidence_chunk_key"], fact["evidence_page"])
    return read_tree(conn, session_id, user_id)
