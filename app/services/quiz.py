"""智能自测的服务层：组卷、判分、错题回填。

职责边界（与组内分工一致）：
    本人（徐张睿）负责：题目数据结构、组卷、取卷、判分、幂等、错题回填事务。
    陈瑀涵负责：Agent 出题质量（app/agents/quiz.py + prompts）。
    沈文驰负责：错题本查询与薄弱度聚合（app/services/wrong_book.py）。

所以这里对「出题」做了一层可替换的钩子：
    优先调用 app.agents.quiz.generate_quiz_items（陈瑀涵的实现）；
    该模块不存在或调用失败时，退化为「从知识点定义反向构造选择题」的确定性算法。
好处是：徐张睿的接口今天就能联调，陈瑀涵的实现一到就自动接管，不用改调用方。

几个刻意的设计：
    1. 答案不出服务端：取卷接口只返回题干与选项，answer/analysis 仅在判分后返回。
    2. 判分幂等：只有 status='ready' 才判；已判过的重复提交直接返回上次结果，
       既不重复加分，也不重复写错题。
    3. 交卷一个事务：分数、逐题结果、错题回填同进同退，避免"分数有了、错题没进库"。
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from typing import Any

from app.db.conn import business_db, transaction

# 每题分值：总分固定 100，按题量均分，四舍五入到两位小数
TOTAL_SCORE = 100.0
OPTION_LETTERS = "ABCD"

# 判断题的等价写法
_TRUE_WORDS = {"对", "正确", "是", "true", "t", "1", "√"}
_FALSE_WORDS = {"错", "错误", "否", "false", "f", "0", "×"}


class QuizError(Exception):
    """业务错误：带 HTTP 状态码，由路由层转成 HTTPException。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# 组卷
# --------------------------------------------------------------------------
def create_test(conn: sqlite3.Connection, *, user_id: int, session_id: int,
                question_count: int = 5, scope_text: str = "") -> int:
    """建一张待出题的卷子，返回 test_id。

    这里只做校验和插入（毫秒级），真正的出题交给后台任务，
    接口可以立刻返回，前端轮询状态即可。
    """
    session = conn.execute(
        "SELECT session_id, user_id, course_name, status FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    # 越权一律 404，不暴露"存在但不属于你"
    if session is None or int(session["user_id"]) != int(user_id):
        raise QuizError("整理任务不存在", 404)
    if session["status"] not in {"success", "partial"}:
        raise QuizError("该任务尚未整理完成，无法出题", 409)

    has_items = conn.execute(
        """SELECT COUNT(*) AS c FROM note_items ni
             JOIN notes n ON n.note_id = ni.note_id
            WHERE n.session_id = ?""",
        (session_id,),
    ).fetchone()["c"]
    if not has_items:
        raise QuizError("该任务没有可用知识点，无法出题", 409)

    cursor = conn.execute(
        """INSERT INTO self_tests (user_id, session_id, course_name, scope_text, question_count)
           VALUES (?, ?, ?, ?, ?)""",
        (int(user_id), int(session_id), session["course_name"] or "", scope_text or "",
         int(question_count)),
    )
    return int(cursor.lastrowid)


def build_items_job(test_id: int) -> None:
    """后台任务：出题并落库。

    刻意自己开连接：FastAPI 的请求级连接在响应结束后会被关闭，
    后台任务不能复用那个对象。
    """
    with business_db() as conn:
        try:
            build_items(conn, test_id)
        except Exception as exc:  # noqa: BLE001 - 出题失败不应让进程崩
            conn.execute(
                "UPDATE self_tests SET status = 'failed', error_message = ? WHERE test_id = ?",
                (str(exc)[:300], test_id),
            )


def build_items(conn: sqlite3.Connection, test_id: int) -> int:
    """按 test 的设置生成题目，成功后把状态推进到 ready。"""
    test = conn.execute("SELECT * FROM self_tests WHERE test_id = ?", (test_id,)).fetchone()
    if test is None:
        raise QuizError("自测不存在", 404)
    if test["status"] in {"ready", "graded"}:
        return int(conn.execute(
            "SELECT COUNT(*) AS c FROM self_test_items WHERE test_id = ?", (test_id,)
        ).fetchone()["c"])

    session_id = test["session_id"]
    count = int(test["question_count"] or 5)
    kps = _load_knowledge_points(conn, session_id)
    if not kps:
        raise QuizError("该任务没有可用知识点")

    # ① 优先用陈瑀涵的 Agent 出题；② 没有就退化为确定性构造
    items = _agent_items(conn, session_id, kps, count) or _template_items(kps, count)

    # 分值分配：不能简单用 100/n（3 题会得到 33.33×3=99.99），
    # 让最后一项吸收余数，保证满分正好 100。
    per_score = round(TOTAL_SCORE / len(items), 2)
    scores = [per_score] * (len(items) - 1)
    scores.append(round(TOTAL_SCORE - per_score * (len(items) - 1), 2))

    with transaction(conn):
        conn.execute("DELETE FROM self_test_items WHERE test_id = ?", (test_id,))
        for seq, (item, score) in enumerate(zip(items, scores), start=1):
            conn.execute(
                """INSERT INTO self_test_items
                   (test_id, seq, knowledge_name, question_type, stem, options_json,
                    answer, analysis, evidence_chunk_key, evidence_page, score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (test_id, seq, item["knowledge_name"], item.get("question_type", "single"),
                 item["stem"], json.dumps(item.get("options", []), ensure_ascii=False),
                 item["answer"], item.get("analysis", ""),
                 item.get("evidence_chunk_key", ""), item.get("evidence_page"),
                 score),
            )
        conn.execute(
            """UPDATE self_tests
                  SET status = 'ready', total_score = ?, question_count = ?, error_message = ''
                WHERE test_id = ?""",
            (round(sum(scores), 2), len(items), test_id),
        )
    return len(items)


def _load_knowledge_points(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    """取该任务的知识点（名称、定义、出处），按重要度排序。"""
    rows = conn.execute(
        """SELECT ni.name, ni.definition, ni.evidence_json, ni.importance
             FROM note_items ni
             JOIN notes n ON n.note_id = ni.note_id
            WHERE n.session_id = ?
            ORDER BY ni.importance DESC, ni.sort_order ASC""",
        (session_id,),
    ).fetchall()

    kps: list[dict] = []
    for row in rows:
        name = _clean_name(row["name"])
        definition = (row["definition"] or "").strip()
        if not name or not definition:
            continue
        evidence: dict = {}
        try:
            parsed = json.loads(row["evidence_json"] or "[]")
            if parsed and isinstance(parsed[0], dict):
                evidence = parsed[0]
        except (json.JSONDecodeError, TypeError):
            evidence = {}
        kps.append({
            "name": name,
            "definition": definition,
            "chunk_key": str(evidence.get("chunk_key") or ""),
            "page": evidence.get("page_num"),
            "slide": evidence.get("slide_index"),
        })
    return kps


def _clean_name(raw: object) -> str:
    """把知识点名压成一个短标题。

    为什么需要：占位实现（无模型密钥）下，知识点名直接取自分块首行，
    可能是一整句话，例如「第3章 软件测试本章讨论软件测试的基本概念与方法」。
    这样的名字会让题干变成一句废话，更要紧的是——错题本按知识点名聚合薄弱度，
    名字不稳定会把同一个知识点拆成好几条统计。

    清洗规则（保守，只做明显安全的截断）：
        1. 遇到分隔符「｜」「|」「。」「换行」只取前段；
        2. 截掉「本章/本讲/本节」之后的说明性文字；
        3. 仍超过 20 字则截断加省略号。
    """
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return ""
    text = re.split(r"[｜|。\n]", text)[0].strip()
    text = re.sub(r"(本章|本讲|本节)\s*.*$", "", text).strip()
    if not text:
        return ""
    return text if len(text) <= 20 else text[:20].rstrip() + "…"


def _agent_items(conn: sqlite3.Connection, session_id: int, kps: list[dict],
                 count: int) -> list[dict] | None:
    """调用陈瑀涵的 Agent 出题模块；不存在或失败都返回 None，由调用方兜底。"""
    try:
        from app.agents import quiz as agent_quiz  # 该模块由陈瑀涵提供
    except Exception:  # noqa: BLE001 - 尚未实现时属于正常情况
        return None

    generate = getattr(agent_quiz, "generate_quiz_items", None)
    if not callable(generate):
        return None
    try:
        items = generate(conn, session_id=session_id, knowledge_points=kps, count=count)
    except Exception:  # noqa: BLE001 - Agent 出题失败不能影响接口可用性
        return None
    if not isinstance(items, list) or not items:
        return None

    # 统一校验 Agent 产出的结构，坏的直接丢弃（不污染题库）
    cleaned: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        stem = str(raw.get("stem") or "").strip()
        answer = str(raw.get("answer") or "").strip().upper()
        options = raw.get("options") or []
        if not stem or answer not in OPTION_LETTERS or len(options) < 2:
            continue
        cleaned.append({
            "knowledge_name": str(raw.get("knowledge_name") or ""),
            "question_type": "single",
            "stem": stem,
            "options": [str(o) for o in options[:4]],
            "answer": answer,
            "analysis": str(raw.get("analysis") or ""),
            "evidence_chunk_key": str(raw.get("evidence_chunk_key") or ""),
            "evidence_page": raw.get("evidence_page"),
        })
    return cleaned or None


def _template_items(kps: list[dict], count: int) -> list[dict]:
    """确定性出题：用知识点定义做正确项，其他知识点定义做干扰项。

    这不是"AI 出题"，而是保证接口可用的兜底方案——题目来自材料原文，
    正确项就是原文定义，因此不会编造。Agent 出题到位后此处自动退居备用。
    """
    picked = kps[:max(1, min(count, len(kps)))]
    others = [k["definition"] for k in kps if k not in picked]
    random.Random(20261120).shuffle(others)

    items: list[dict] = []
    for idx, kp in enumerate(picked):
        definition = _shorten(kp["definition"], 90)
        distractors: list[str] = []
        # 干扰项优先用其他知识点的定义（更像"概念混淆"）
        for candidate in others:
            short = _shorten(candidate, 90)
            if short and short != definition:
                distractors.append(f"{short}（该表述属于其他知识点）")
            if len(distractors) >= 3:
                break
        while len(distractors) < 3:
            distractors.append("以上说法均不适用于本知识点")

        options = [definition] + distractors[:3]
        # 用知识点名做种子，保证同一次组卷内选项顺序稳定、可复现
        random.Random(f"{kp['name']}-{idx}").shuffle(options)
        answer = OPTION_LETTERS[options.index(definition)]

        page = kp.get("page") or kp.get("slide")
        loc = f"第 {page} 页" if kp.get("page") else (f"第 {kp['slide']} 张幻灯片"
                                                     if kp.get("slide") else "出处见原文")
        items.append({
            "knowledge_name": kp["name"],
            "question_type": "single",
            "stem": f"关于「{kp['name']}」，下列说法正确的是？",
            "options": options,
            "answer": answer,
            "analysis": f"正确表述来自课件原文：{definition}（{loc}）",
            "evidence_chunk_key": kp.get("chunk_key", ""),
            "evidence_page": kp.get("page"),
        })
    return items


def _shorten(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


# --------------------------------------------------------------------------
# 取卷
# --------------------------------------------------------------------------
def _own_test(conn: sqlite3.Connection, test_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM self_tests WHERE test_id = ?", (test_id,)).fetchone()
    if row is None or int(row["user_id"]) != int(user_id):
        raise QuizError("自测不存在", 404)
    return row


def get_test(conn: sqlite3.Connection, *, test_id: int, user_id: int) -> dict:
    """取卷。未判分时不下发答案与解析。"""
    test = _own_test(conn, test_id, user_id)
    graded = test["status"] == "graded"
    rows = conn.execute(
        "SELECT * FROM self_test_items WHERE test_id = ? ORDER BY seq", (test_id,)
    ).fetchall()

    items: list[dict] = []
    for row in rows:
        item = {
            "item_id": int(row["item_id"]),
            "seq": int(row["seq"]),
            "question_type": row["question_type"],
            "stem": row["stem"],
            "options": json.loads(row["options_json"] or "[]"),
            "knowledge_name": row["knowledge_name"],
        }
        if graded:
            item.update({
                "answer": row["answer"],
                # 与前端约定字段对齐：结果页读的是 correct_answer（自测/错题两页共用同一套渲染）
                "correct_answer": row["answer"],
                "analysis": row["analysis"],
                "user_answer": row["user_answer"] or "",
                "is_correct": bool(row["is_correct"]),
                "evidence_page": row["evidence_page"],
            })
        items.append(item)

    wrong_count = conn.execute(
        "SELECT COUNT(*) AS c FROM wrong_questions WHERE user_id = ? AND source_type = 'self_test' "
        "AND source_id IN (SELECT item_id FROM self_test_items WHERE test_id = ?)",
        (int(user_id), test_id),
    ).fetchone()["c"] if graded else 0

    return {
        "test_id": int(test["test_id"]),
        "course_name": test["course_name"],
        "status": test["status"],
        "question_count": len(items),
        "total_score": float(test["total_score"] or TOTAL_SCORE),
        "score": float(test["score"] or 0),
        "correct_count": int(test["correct_count"] or 0),
        "error_message": test["error_message"] or "",
        "created_at": test["created_at"],
        "submitted_at": test["submitted_at"],
        "wrong_count": wrong_count,
        "items": items,
    }


def list_tests(conn: sqlite3.Connection, *, user_id: int, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT test_id, course_name, status, question_count, total_score, score,
                  correct_count, created_at, submitted_at
             FROM self_tests WHERE user_id = ? ORDER BY test_id DESC LIMIT ?""",
        (int(user_id), int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


# --------------------------------------------------------------------------
# 交卷判分
# --------------------------------------------------------------------------
def submit_test(conn: sqlite3.Connection, *, test_id: int, user_id: int,
                answers: list[dict]) -> dict:
    """判分 + 错题回填，整个过程一个事务、且只执行一次。

    幂等：status 已是 graded 时直接返回上次结果，不重复加分、不重复记错题。
    """
    test = _own_test(conn, test_id, user_id)
    if test["status"] == "failed":
        raise QuizError("该自测出题失败，请重新组卷", 409)

    # 判过分的卷子不再判第二次。
    # 原因很实际：学生在页面上手抖点两下「交卷」，如果每次都重新判，
    # 分数会加两遍、错题的 wrong_count 也会翻倍，按知识点聚合出来的薄弱度直接失真。
    # 所以这里不看这次提交了什么，直接返回上一次的结果。
    if test["status"] == "graded":
        return get_test(conn, test_id=test_id, user_id=user_id)

    answer_map = {int(a["item_id"]): str(a.get("answer") or "") for a in answers if a.get("item_id")}
    rows = conn.execute(
        "SELECT * FROM self_test_items WHERE test_id = ? ORDER BY seq", (test_id,)
    ).fetchall()

    correct_count = 0
    gained = 0.0
    wrong_items: list[sqlite3.Row] = []

    # 分数、逐题结果、错题回填必须在同一个事务里。
    # 中间任何一步失败就整体回滚——不能出现「分数有了、错题没进库」这种半截状态，
    # 那种状态下学生看到 80 分却找不到错题，而且没有任何报错提示，最难查。
    with transaction(conn):
        for row in rows:
            item_id = int(row["item_id"])
            user_answer = answer_map.get(item_id, "")
            is_correct = _judge(row["question_type"], row["answer"], user_answer)
            score = float(row["score"] or 0) if is_correct else 0.0

            conn.execute(
                """UPDATE self_test_items
                      SET user_answer = ?, is_correct = ?, score = ?,
                          answered_at = CURRENT_TIMESTAMP
                    WHERE item_id = ?""",
                (user_answer, 1 if is_correct else 0, score, item_id),
            )
            if is_correct:
                correct_count += 1
                gained += score
            else:
                wrong_items.append(row)

        # 错题回填：靠 (user_id, source_type, source_id) 这个唯一键去重。
        # 一道题永远只有一条记录：第一次答错是 INSERT，之后再答错走 UPDATE，
        # wrong_count 加一、连对清零、已掌握状态撤销。
        # 反面教材：如果每次答错都插一行，错题本会变成一长串重复题，
        # 按知识点聚合出来的「薄弱度」也会算错——同一个知识点显示错 5 次，
        # 其实只是同一道题错了 5 次。
        for row in wrong_items:
            conn.execute(
                """INSERT INTO wrong_questions
                     (user_id, knowledge_name, source_type, source_id, question_stem,
                      correct_answer, analysis, evidence_chunk_key, evidence_page)
                   VALUES (?, ?, 'self_test', ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, source_type, source_id) DO UPDATE SET
                     wrong_count = wrong_count + 1,
                     correct_streak = 0,
                     mastered = 0,
                     last_wrong_at = CURRENT_TIMESTAMP""",
                (int(user_id), row["knowledge_name"] or "", int(row["item_id"]),
                 row["stem"], row["answer"], row["analysis"],
                 row["evidence_chunk_key"], row["evidence_page"]),
            )

        conn.execute(
            """UPDATE self_tests
                  SET status = 'graded', score = ?, correct_count = ?,
                      submitted_at = CURRENT_TIMESTAMP, graded_at = CURRENT_TIMESTAMP
                WHERE test_id = ?""",
            (round(gained, 2), correct_count, test_id),
        )

    result = get_test(conn, test_id=test_id, user_id=user_id)
    result["wrong_count"] = len(wrong_items)
    return result


def _judge(question_type: str, correct: str, user_answer: str) -> bool:
    """判分规则：单选按字母、判断按等价词，其余按文本归一化比较。"""
    correct_norm = _normalize(correct)
    user_norm = _normalize(user_answer)
    if not user_norm:
        return False
    if question_type == "judge":
        return _judge_bool(correct_norm) == _judge_bool(user_norm)
    return correct_norm == user_norm


def _normalize(text: str) -> str:
    """全角转半角 + 去空白 + 小写，避免「Ｂ」与「b」被误判。"""
    chars = []
    for ch in str(text or ""):
        code = ord(ch)
        if code == 0x3000:
            code = 0x20
        elif 0xFF01 <= code <= 0xFF5E:
            code -= 0xFEE0
        chars.append(chr(code))
    return "".join(chars).strip().lower()


def _judge_bool(text: str) -> bool | None:
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None
