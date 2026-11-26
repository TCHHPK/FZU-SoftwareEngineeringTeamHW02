"""考前冲刺计划（K2）业务逻辑。

契约：docs/契约-v1.3.md 3.3。硬约束（全部在 ``build_plan`` 里落实）：
    1. 每天不超过 5 项，总时长不超过 daily_minutes；
    2. 同一知识点 48 小时内不重复排（相邻两天不出现同名知识点）；
    3. 最后两天只排「高频错题」或「高重要度」知识点；
    4. 每条任务必须带 reason（写清为什么排它）。

错误口径与契约一致：
    400 —— exam_date 格式错误或早于今天、daily_minutes ≤ 0；
    404 —— 任务不存在或不属于本人（越权一律 404）。

本文件主责：沈文驰。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

# 权重与契约 3.3 的响应示例保持一致（前端会原样展示）
WEIGHTS: dict[str, float] = {"weakness": 0.5, "importance": 0.3, "urgency": 0.2}

MAX_ITEMS_PER_DAY = 5      # 每天最多 5 项
GAP_DAYS = 2               # 同一知识点 48 小时内不重复
HIGH_IMPORTANCE = 4        # 最后两天视为「高重要度」的门槛（5 分制）
HIGH_WRONG_COUNT = 2       # 最后两天视为「高频错题」的门槛


class PlanError(Exception):
    """业务错误：带 HTTP 状态码，由路由层转成 HTTPException。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _parse_exam_date(raw: str) -> date:
    try:
        return date.fromisoformat(str(raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise PlanError("exam_date 格式错误，应为 YYYY-MM-DD", 400) from exc


def _urgency(due_at: str | None) -> float:
    """到期紧迫度：未排期按「现在就该复习」算，48 小时内最高。"""
    if not due_at:
        return 1.0
    try:
        due = datetime.fromisoformat(str(due_at))
    except ValueError:
        return 0.5
    if due.tzinfo is None:  # 库里的调度时间统一按 UTC 存
        due = due.replace(tzinfo=timezone.utc)
    hours = (due - datetime.now(timezone.utc)).total_seconds() / 3600
    if hours <= 48:
        return 1.0
    if hours <= 24 * 7:
        return 0.4
    return 0.1


def _knowledge_points(conn: sqlite3.Connection, session_id: int) -> dict[str, int]:
    """本任务的知识点及其最高重要度（同名合并，避免重复排）。"""
    rows = conn.execute(
        "SELECT ni.name, ni.importance"
        "  FROM note_items ni"
        "  JOIN notes n ON n.note_id = ni.note_id"
        " WHERE n.session_id = :sid"
        " ORDER BY ni.importance DESC, ni.sort_order, ni.item_id",
        {"sid": int(session_id)},
    ).fetchall()
    merged: dict[str, int] = {}
    for row in rows:
        name = (row["name"] or "").strip()
        if not name:
            continue
        importance = int(row["importance"] or 3)
        merged[name] = max(merged.get(name, 0), importance)
    return merged


def _wrong_stats(conn: sqlite3.Connection, user_id: int) -> dict[str, dict]:
    """按知识点聚合错题次数与最早到期时间（跨任务汇总用户自己的错题）。"""
    rows = conn.execute(
        "SELECT knowledge_name, SUM(wrong_count) AS wc, MIN(due_at) AS due_at"
        "  FROM wrong_questions"
        " WHERE user_id = :uid"
        " GROUP BY knowledge_name",
        {"uid": int(user_id)},
    ).fetchall()
    return {
        (r["knowledge_name"] or ""): {
            "wrong_count": int(r["wc"] or 0),
            "due_at": r["due_at"],
        }
        for r in rows
    }


def _candidates(conn: sqlite3.Connection, *, user_id: int, session_id: int) -> list[dict]:
    knowledge = _knowledge_points(conn, session_id)
    stats = _wrong_stats(conn, user_id)

    candidates: list[dict] = []
    for name, importance in knowledge.items():
        stat = stats.get(name, {})
        wrong_count = int(stat.get("wrong_count") or 0)
        urgency = _urgency(stat.get("due_at"))
        score = (WEIGHTS["weakness"] * min(wrong_count, 5) / 5
                 + WEIGHTS["importance"] * importance / 5
                 + WEIGHTS["urgency"] * urgency)
        candidates.append({
            "knowledge_name": name,
            "importance": importance,
            "wrong_count": wrong_count,
            "due_at": stat.get("due_at"),
            "urgency": urgency,
            "score": round(score, 4),
        })
    candidates.sort(key=lambda c: (-c["score"], -c["importance"], c["knowledge_name"]))
    return candidates


def _reason(candidate: dict, *, last_two: bool) -> str:
    bits: list[str] = []
    wrong_count = int(candidate["wrong_count"])
    if wrong_count:
        bits.append(f"累计答错 {wrong_count} 次")
    if candidate["urgency"] >= 1.0:
        bits.append("当前已到期或尚未排期")
    elif candidate["urgency"] >= 0.4:
        bits.append("一周内到期")
    bits.append(f"重要度 {candidate['importance']}/5")
    if last_two:
        bits.append("冲刺最后两天只排高频错题与高重要度")
    return "；".join(bits)


def build_plan(conn: sqlite3.Connection, *, user_id: int, session_id: int,
               exam_date: str, daily_minutes: int) -> dict:
    """生成冲刺计划。返回契约 3.3 的 data 结构（日期一律 ISO8601 字符串）。"""
    exam = _parse_exam_date(exam_date)
    if exam < date.today():
        raise PlanError("考试日期早于今天，无法排计划", 400)
    if int(daily_minutes) <= 0:
        raise PlanError("daily_minutes 必须大于 0", 400)

    session = conn.execute(
        "SELECT user_id FROM sessions WHERE session_id = ?", (int(session_id),),
    ).fetchone()
    if session is None or int(session["user_id"]) != int(user_id):
        raise PlanError("任务不存在或无权访问", 404)

    candidates = _candidates(conn, user_id=int(user_id), session_id=int(session_id))

    today = date.today()
    plan_dates: list[date] = []
    cursor = today
    while cursor < exam:  # 考前冲刺：不排考试当天
        plan_dates.append(cursor)
        cursor += timedelta(days=1)
    if not plan_dates:  # 考试就是今天：只排今天
        plan_dates = [today]

    per_item = max(1, int(daily_minutes) // MAX_ITEMS_PER_DAY)
    last_used: dict[str, int] = {}
    days: list[dict] = []

    for day_index, day in enumerate(plan_dates):
        last_two = day_index >= len(plan_dates) - 2
        picked: list[dict] = []
        used_minutes = 0

        for candidate in candidates:
            if len(picked) >= MAX_ITEMS_PER_DAY:
                break
            name = candidate["knowledge_name"]
            # 48 小时规则：同一知识点至少隔一天才能再排
            if day_index - last_used.get(name, -10 ** 6) < GAP_DAYS:
                continue
            if last_two and not (candidate["wrong_count"] >= HIGH_WRONG_COUNT
                                 or candidate["importance"] >= HIGH_IMPORTANCE):
                continue
            if used_minutes + per_item > int(daily_minutes):
                break
            picked.append({
                "knowledge_name": name,
                "minutes": per_item,
                "reason": _reason(candidate, last_two=last_two),
            })
            used_minutes += per_item

        for item in picked:
            last_used[item["knowledge_name"]] = day_index
        if picked:
            days.append({
                "date": day.isoformat(),
                "total_minutes": used_minutes,
                "items": picked,
            })

    return {
        "days": days,
        "exam_date": exam.isoformat(),
        "weights": dict(WEIGHTS),
    }
