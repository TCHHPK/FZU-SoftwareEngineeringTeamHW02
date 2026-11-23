"""验证 v1.2.0 老库能否直接升到 v1.3.0（迁移 003）。

为什么要这么绕：
    直接新建库，字段一开始就在，测不出「老库升级」。
    所以先建一个当前结构的库，再把 003 引入的六列、session_traces 表、
    两个索引全部删掉，插入一个用户和一条错题，构造成真实的 v1.2.0 老库，
    然后跑 init_databases()，看它能不能把结构补回来、老数据一条不少。

用法：python scripts/verify_migration_003.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NEW_COLUMNS = ["state", "stability", "difficulty", "due_at", "review_count", "last_review_at"]
TABLES = ("users", "sessions", "self_tests", "wrong_questions", "note_items")


def dump(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db))
    out = {}
    for table in TABLES:
        try:
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            out[table] = -1
    conn.close()
    return out


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="upgrade-"))
    db = tmp / "business.db"
    os.environ["STORAGE_DIR"] = str(tmp)
    os.environ["BUSINESS_DB"] = str(db)
    os.environ["KB_DB"] = str(tmp / "kb.db")

    from app.db.conn import init_databases

    print("[1/6] 建一个 v1.3 结构的库（作为地基）")
    init_databases()

    print("[2/6] 回退成 v1.2.0 老库：删掉 003 引入的列/表/索引")
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = OFF")
    # 顺序很关键：索引引用了 state 列，必须先删索引，否则 DROP COLUMN 会报
    # "error in index idx_wq_state after drop column"
    conn.execute("DROP INDEX IF EXISTS idx_wq_due")
    conn.execute("DROP INDEX IF EXISTS idx_wq_state")
    conn.execute("DROP INDEX IF EXISTS idx_trace_session")
    conn.execute("DROP TABLE IF EXISTS session_traces")
    for col in NEW_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE wrong_questions DROP COLUMN {col}")
        except sqlite3.OperationalError as exc:
            print(f"      无法删除 {col}（{exc}），此环境的 SQLite 不支持 DROP COLUMN")
            return 1
    # 插一条老数据，确认升级不会动它
    conn.execute(
        """INSERT INTO users (username, password_hash, nickname, role)
           VALUES ('legacy_user', 'x', '老用户', 'student')"""
    )
    uid = conn.execute("SELECT user_id FROM users WHERE username = 'legacy_user'").fetchone()[0]
    conn.execute(
        """INSERT INTO wrong_questions
             (user_id, knowledge_name, source_type, source_id, question_stem,
              correct_answer, analysis, evidence_chunk_key, evidence_page,
              wrong_count, correct_streak, mastered)
           VALUES (?, '等价类划分', 'self_test', 999, '老题干', 'A', '老解析',
                   'd1-p1-c1', 1, 3, 1, 0)""",
        (uid,),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(wrong_questions)")}
    has_traces = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='session_traces'"
    ).fetchone()[0]
    conn.close()
    missing = [c for c in NEW_COLUMNS if c not in cols]
    print(f"      老库状态：wrong_questions {len(cols)} 列、缺 {len(missing)} 个新字段、"
          f"session_traces {'不存在' if not has_traces else '仍存在'}")
    if not missing or has_traces:
        print("[失败] 没能构造出真正的老库，测试无意义")
        return 1

    before = dump(db)
    print(f"      升级前条数：{before}")

    print("[3/6] 执行 init_databases()（等同线上升级命令，未加 --reset）")
    init_databases()

    print("[4/6] 再执行一次（幂等性：不应报 duplicate column）")
    init_databases()

    print("[5/6] 校验结构")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    info = {r["name"]: r for r in conn.execute("PRAGMA table_info(wrong_questions)")}
    failed = 0
    for col in NEW_COLUMNS:
        ok = col in info
        failed += 0 if ok else 1
        print(f"      {'OK  ' if ok else 'FAIL'} wrong_questions.{col:<15}"
              f" 默认 {info[col]['dflt_value'] if ok else '-'}")

    has_traces = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='session_traces'"
    ).fetchone()[0]
    failed += 0 if has_traces else 1
    trace_cols = [r["name"] for r in conn.execute("PRAGMA table_info(session_traces)")]
    print(f"      {'OK  ' if has_traces else 'FAIL'} session_traces（{len(trace_cols)} 列："
          f"{'、'.join(trace_cols)}）")

    idx = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    for name in ("idx_wq_due", "idx_trace_session"):
        ok = name in idx
        failed += 0 if ok else 1
        print(f"      {'OK  ' if ok else 'FAIL'} 索引 {name}")

    print("[6/6] 校验老数据")
    after = dump(db)
    same = all(before[k] == after[k] for k in before)
    failed += 0 if same else 1
    print(f"      {'OK  ' if same else 'FAIL'} 条数不变：升级前 {before}，升级后 {after}")

    row = conn.execute(
        """SELECT wrong_count, correct_streak, state, stability, difficulty, due_at, review_count
             FROM wrong_questions WHERE source_id = 999"""
    ).fetchone()
    ok = (row is not None and int(row["wrong_count"]) == 3 and int(row["correct_streak"]) == 1
          and row["state"] == "new" and float(row["stability"]) == 0.0
          and row["due_at"] is None and int(row["review_count"]) == 0)
    failed += 0 if ok else 1
    if row is None:
        print("      FAIL 老错题不见了")
    else:
        print(f"      {'OK  ' if ok else 'FAIL'} 老错题保留且补默认值：wrong_count={row['wrong_count']}、"
              f"streak={row['correct_streak']}、state={row['state']}、due_at={row['due_at']}")
    conn.close()

    print()
    print("老库升级验证通过" if failed == 0 else f"有 {failed} 项失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
