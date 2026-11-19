"""U13/U14/U15 数据迁移回归；使用独立临时数据库。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import conn as db


EXPECTED = {"self_tests", "self_test_items", "wrong_questions", "mindmap_nodes"}


def _tables(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_learning_loop_schema_and_old_database_upgrade(tmp_path, monkeypatch):
    business = tmp_path / "business.db"
    kb = tmp_path / "kb.db"
    monkeypatch.setattr(db, "BUSINESS_DB", business)
    monkeypatch.setattr(db, "KB_DB", kb)

    # 模拟迁移前已存在的生产业务库及记录。
    schema = db.SCHEMA_PATH.read_text(encoding="utf-8")
    pre_learning = schema.split("-- 学习闭环（U13", 1)[0]
    with sqlite3.connect(business) as old_conn:
        old_conn.executescript(pre_learning)
        old_conn.execute("INSERT INTO users(user_id, username, password_hash) VALUES (1,'student','hash')")
        old_conn.execute("INSERT INTO sessions(session_id, user_id, course_name) VALUES (7,1,'软件工程')")

    db.init_databases()
    db.init_databases()  # 可重复执行，无 schema 冲突
    with db.business_db() as con:
        assert EXPECTED.issubset(_tables(con))
        assert con.execute("SELECT course_name FROM sessions WHERE session_id=7").fetchone()[0] == '软件工程'
        con.execute("INSERT INTO self_tests(user_id,session_id) VALUES (1,7)")
        con.execute("INSERT INTO self_test_items(test_id,stem,answer) VALUES (1,'题目','B')")
        con.execute("INSERT INTO wrong_questions(user_id,knowledge_name,source_id) VALUES (1,'UML',1)")
        con.execute("INSERT INTO mindmap_nodes(session_id,user_id,name) VALUES (7,1,'根节点')")
        con.execute("INSERT INTO mindmap_nodes(session_id,user_id,parent_id,name) VALUES (7,1,1,'子节点')")
        assert con.execute("SELECT COUNT(*) FROM mindmap_nodes").fetchone()[0] == 2
        # 唯一键、外键约束真实生效。
        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO wrong_questions(user_id,knowledge_name,source_id) VALUES (1,'UML',1)")
        con.execute("DELETE FROM sessions WHERE session_id = 7")
        assert con.execute("SELECT COUNT(*) FROM mindmap_nodes").fetchone()[0] == 0
        assert con.execute("SELECT session_id FROM self_tests WHERE test_id = 1").fetchone()[0] is None

    with db.kb_db() as con:
        assert EXPECTED.isdisjoint(_tables(con))


def test_fresh_install_creates_learning_loop_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "BUSINESS_DB", tmp_path / "new.db")
    monkeypatch.setattr(db, "KB_DB", tmp_path / "new_kb.db")
    db.init_databases()
    with db.business_db() as con:
        assert EXPECTED.issubset(_tables(con))
        expected_indexes = {'idx_sti_test', 'idx_wq_user_kp', 'idx_mn_session'}
        actual_indexes = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        assert expected_indexes.issubset(actual_indexes)
