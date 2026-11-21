"""错题本（U13）业务逻辑。

职责边界（按《三功能开发分工与接口契约》第五节）：
    - 错题的沉淀、重做判分、掌握状态追踪、薄弱度聚合。
    - 不负责出题与组卷（自测模块），不负责前端渲染。

数据来源：自测交卷判分后，由 routes_self_test 在同一事务里调用
``add_wrong_question`` 入库；本模块不主动开启事务，以便调用方整体回滚，
避免出现「分数已写、错题没进库」的不一致。

判分规则（契约 4.2，写死避免各人理解不同）：
    - 单选 single：答案字符串完全相等（大小写、全半角归一化后比较），空答案记错。
    - 判断 judge：「对/错」「true/false」「1/0」统一映射后比较，空答案记错。
    - 简答 short：本期不启用。
"""

from __future__ import annotations

import sqlite3
import json
import unicodedata

from app.db.conn import transaction

# 连续答对 2 次自动标记「已掌握」（契约验收路径②）
MASTERY_THRESHOLD = 2

# 判断题答案归一化后 → 统一布尔值
_TRUE = {"对", "正确", "是", "true", "t", "1", "yes", "y"}
_FALSE = {"错", "错误", "否", "false", "f", "0", "no", "n"}
_JUDGE_HINT = _TRUE | _FALSE


# --------------------------------------------------------------------------
# 判分（可被自测模块复用，保证判分口径唯一）
# --------------------------------------------------------------------------
def _norm(text: str | None) -> str:
    """归一化：全角字母数字 → 半角，压缩空白，转小写。"""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", text)  # 全角→半角
    text = text.strip().lower()
    text = " ".join(text.split())  # 压缩内部空白
    return text


def _judge_value(text: str) -> bool | None:
    """把判断题答案映射为布尔值；非判断题表述返回 None。"""
    n = _norm(text)
    if n in _TRUE:
        return True
    if n in _FALSE:
        return False
    return None


def judge_answer(correct_answer: str, user_answer: str,
                 question_type: str | None = None) -> bool:
    """判分：契约 4.2。

    question_type 缺省时按 correct_answer 启发式推断——落在判断值集合里即按判断处理。
    wrong_questions 表当前不存题型，重做接口走启发式；自测判分若已知题型可显式传入，
    确保两处口径完全一致。
    """
    # 空答案记错，不抛异常
    if user_answer is None or _norm(user_answer) == "":
        return False

    is_judge = question_type == "judge" or (
        question_type is None and _norm(correct_answer) in _JUDGE_HINT
    )
    if is_judge:
        cv, uv = _judge_value(correct_answer), _judge_value(user_answer)
        # 任一侧识别不出判断值时退化为字符串相等，避免误判
        if cv is None or uv is None:
            return _norm(correct_answer) == _norm(user_answer)
        return cv == uv
    return _norm(correct_answer) == _norm(user_answer)


# --------------------------------------------------------------------------
# 序列化
# --------------------------------------------------------------------------
def _row_to_out(row: dict) -> dict:
    return {
        "wrong_id": int(row["wrong_id"]),
        "knowledge_name": row["knowledge_name"] or "",
        "source_type": row["source_type"] or "self_test",
        "source_id": int(row["source_id"]),
        "question_stem": row["question_stem"] or "",
        "correct_answer": row["correct_answer"] or "",
        "analysis": row["analysis"] or "",
        "evidence_chunk_key": row["evidence_chunk_key"] or "",
        "evidence_page": row["evidence_page"],
        "wrong_count": int(row["wrong_count"] or 0),
        "correct_streak": int(row["correct_streak"] or 0),
        "mastered": bool(row["mastered"]),
        "last_wrong_at": row["last_wrong_at"] or "",
        "created_at": row["created_at"] or "",
    }


def _weakness_label(unmastered: int, wrong_count: int) -> str:
    """薄弱度先按错题数排序（契约 2.2：先不调参，按错题数）。"""
    if unmastered <= 0:
        return "已掌握"
    if wrong_count >= 3 or unmastered >= 2:
        return "高"
    if wrong_count >= 2:
        return "中"
    return "低"


# --------------------------------------------------------------------------
# 读：列表 + 薄弱度聚合 / 详情
# --------------------------------------------------------------------------
def list_wrong_questions(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    knowledge_name: str | None = None,
    mastered: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """错题列表 + 按知识点的薄弱度聚合。

    列表按最近答错时间倒序；薄弱度按未掌握数、再按错题数倒序（契约 2.2）。
    筛选：knowledge_name 模糊匹配、mastered 0/1（MVP 基础筛选，多维筛选见降级方案）。
    """
    where = ["user_id = :uid"]
    params: dict = {"uid": int(user_id)}
    if knowledge_name:
        where.append("knowledge_name LIKE :kn")
        params["kn"] = f"%{knowledge_name}%"
    if mastered is not None:
        where.append("mastered = :m")
        params["m"] = 1 if mastered else 0
    where_sql = " AND ".join(where)

    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM wrong_questions WHERE {where_sql}", params
    ).fetchone()["c"]

    rows = conn.execute(
        f"SELECT * FROM wrong_questions WHERE {where_sql}"
        " ORDER BY last_wrong_at DESC, wrong_id DESC LIMIT :lim OFFSET :off",
        {**params, "lim": int(limit), "off": int(offset)},
    ).fetchall()
    items = [_row_to_out(dict(r)) for r in rows]

    # 薄弱度聚合（全量统计，不受列表 mastered 筛选影响；可按知识点名称筛选）
    agg_where = ["user_id = :uid"]
    agg_params: dict = {"uid": int(user_id)}
    if knowledge_name:
        agg_where.append("knowledge_name LIKE :kn")
        agg_params["kn"] = f"%{knowledge_name}%"
    agg_sql = " AND ".join(agg_where)
    agg_rows = conn.execute(
        f"SELECT knowledge_name,"
        " SUM(wrong_count) AS wrong_count,"
        " SUM(CASE WHEN mastered = 1 THEN 1 ELSE 0 END) AS mastered_count,"
        " SUM(CASE WHEN mastered = 0 THEN 1 ELSE 0 END) AS unmastered_count,"
        " MAX(last_wrong_at) AS last_wrong_at"
        f" FROM wrong_questions WHERE {agg_sql}"
        " GROUP BY knowledge_name"
        " ORDER BY unmastered_count DESC, wrong_count DESC, knowledge_name ASC",
        agg_params,
    ).fetchall()
    weak_points = []
    for r in agg_rows:
        d = dict(r)
        unmastered = int(d["unmastered_count"] or 0)
        wc = int(d["wrong_count"] or 0)
        weak_points.append({
            "knowledge_name": d["knowledge_name"] or "",
            "wrong_count": wc,
            "mastered_count": int(d["mastered_count"] or 0),
            "unmastered_count": unmastered,
            "last_wrong_at": d["last_wrong_at"] or "",
            "weakness": _weakness_label(unmastered, wc),
        })

    return {"items": items, "weak_points": weak_points, "total": int(total)}


def get_wrong_question(conn: sqlite3.Connection, user_id: int, wrong_id: int) -> dict | None:
    """错题详情；越权（不是自己的）一律返回 None，由路由层转 404。

    额外带上 options：错题本页的重做界面需要选项才能渲染单选框。
    选项存在 self_test_items.options_json 里（source_type='self_test' 时
    source_id 就是 item_id）；找不到就返回空数组，前端退化为文本输入。
    """
    row = conn.execute(
        "SELECT * FROM wrong_questions WHERE wrong_id = :wid AND user_id = :uid",
        {"wid": int(wrong_id), "uid": int(user_id)},
    ).fetchone()
    if row is None:
        return None

    data = _row_to_out(dict(row))
    data["options"] = []
    data["question_type"] = "single"
    if (data["source_type"] or "") == "self_test":
        item = conn.execute(
            "SELECT options_json, question_type FROM self_test_items WHERE item_id = :iid",
            {"iid": int(data["source_id"])},
        ).fetchone()
        if item is not None:
            try:
                parsed = json.loads(item["options_json"] or "[]")
                data["options"] = [str(x) for x in parsed] if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                data["options"] = []
            data["question_type"] = item["question_type"] or "single"
    return data


# --------------------------------------------------------------------------
# 写：重做判分 / 入库
# --------------------------------------------------------------------------
def retry_wrong_question(conn: sqlite3.Connection, user_id: int,
                         wrong_id: int, answer: str) -> dict | None:
    """重做一题：判分 → 更新连对次数与掌握状态 → 返回结果。

    规则（契约验收路径②）：
      - 答对：correct_streak += 1；达到 MASTERY_THRESHOLD → mastered = 1。
      - 答错：correct_streak = 0，wrong_count += 1，mastered = 0，刷新 last_wrong_at。
    判分与状态更新在一个事务里，原子完成。
    """
    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM wrong_questions WHERE wrong_id = :wid AND user_id = :uid",
            {"wid": int(wrong_id), "uid": int(user_id)},
        ).fetchone()
        if row is None:
            return None
        rec = dict(row)
        correct = judge_answer(rec["correct_answer"], answer)

        if correct:
            new_streak = int(rec["correct_streak"] or 0) + 1
            mastered = 1 if new_streak >= MASTERY_THRESHOLD else int(rec["mastered"] or 0)
            # 答对不增加 wrong_count，也不刷新 last_wrong_at
            conn.execute(
                "UPDATE wrong_questions SET correct_streak = :s, mastered = :m"
                " WHERE wrong_id = :wid",
                {"s": new_streak, "m": mastered, "wid": int(wrong_id)},
            )
        else:
            conn.execute(
                "UPDATE wrong_questions"
                " SET correct_streak = 0, mastered = 0,"
                " wrong_count = wrong_count + 1, last_wrong_at = CURRENT_TIMESTAMP"
                " WHERE wrong_id = :wid",
                {"wid": int(wrong_id)},
            )

        fresh = conn.execute(
            "SELECT * FROM wrong_questions WHERE wrong_id = :wid",
            {"wid": int(wrong_id)},
        ).fetchone()
        out = _row_to_out(dict(fresh))

    return {
        "is_correct": correct,
        "correct_answer": out["correct_answer"],
        "analysis": out["analysis"],
        "evidence_chunk_key": out["evidence_chunk_key"],
        "evidence_page": out["evidence_page"],
        "correct_streak": out["correct_streak"],
        "mastered": out["mastered"],
        "mastery_threshold": MASTERY_THRESHOLD,
    }


def add_wrong_question(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    knowledge_name: str,
    source_type: str = "self_test",
    source_id: int,
    question_stem: str = "",
    correct_answer: str = "",
    analysis: str = "",
    evidence_chunk_key: str = "",
    evidence_page: int | None = None,
) -> int:
    """错题入库（供自测交卷判分在同一事务内调用）。

    唯一键 (user_id, source_type, source_id) 去重：
      - 首次入库：插入一条，wrong_count = 1。
      - 重复答错：wrong_count += 1，并把连对/掌握状态清零（又错说明没掌握），
        同时用最新题目内容覆盖（出处/解析可能随版本更新）。

    不主动开启事务：调用方（交卷接口）已在事务中，必须整体回滚才能保证
    「分数有、错题没进库」不出现。返回 wrong_id。
    """
    cur = conn.execute(
        "INSERT INTO wrong_questions"
        " (user_id, knowledge_name, source_type, source_id, question_stem,"
        "  correct_answer, analysis, evidence_chunk_key, evidence_page,"
        "  wrong_count, correct_streak, mastered)"
        " VALUES"
        " (:uid, :kn, :st, :sid, :qs, :ca, :an, :eck, :ep, 1, 0, 0)"
        " ON CONFLICT(user_id, source_type, source_id) DO UPDATE SET"
        "   wrong_count = wrong_count + 1,"
        "   correct_streak = 0,"
        "   mastered = 0,"
        "   last_wrong_at = CURRENT_TIMESTAMP,"
        "   question_stem = excluded.question_stem,"
        "   correct_answer = excluded.correct_answer,"
        "   analysis = excluded.analysis,"
        "   evidence_chunk_key = excluded.evidence_chunk_key,"
        "   evidence_page = excluded.evidence_page"
        " RETURNING wrong_id",
        {
            "uid": int(user_id),
            "kn": knowledge_name or "",
            "st": source_type or "self_test",
            "sid": int(source_id),
            "qs": question_stem or "",
            "ca": correct_answer or "",
            "an": analysis or "",
            "eck": evidence_chunk_key or "",
            "ep": evidence_page,
        },
    )
    row = cur.fetchone()
    return int(row["wrong_id"])
