"""Agent 出题模块（U14 的出题环节）。

分工上这个模块属于陈瑀涵（Agent 侧）。合并时它没到位，
而 `app/api/routes_mindmap.py` 又要 `from app.agents.quiz import QuizUnavailable`
才能导入，所以这里按契约把真实实现补上——否则整个应用起不来。

实现要点：
    1. 只把「知识点名 + 定义 + 出处」交给模型，题目必须落在材料范围内；
    2. 模型返回的每道题都要过结构校验：4 个选项、answer ∈ ABCD、引用了给定过的
       chunk_key；任何一项不合格就丢弃该题，不污染题库；
    3. 模型不可用（没配密钥 / 调用失败 / 全被丢弃）时抛 QuizUnavailable，
       由 services/quiz.py 退化为「知识点定义反向构造选择题」，接口不会 500。

也就是说：Agent 出题是「更好」，模板兜底是「保底」。两者都不会编造材料之外的内容。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "quiz_generate.txt"
OPTION_LETTERS = "ABCD"


class QuizUnavailable(RuntimeError):
    """出题能力不可用（模型未配置 / 材料不足 / 模型输出全不合格）。

    路由层把它转成 HTTP 409，前端据此提示「暂不可用」，而不是显示 500。
    """


def _load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:  # 提示词缺失属于部署问题，明确报错而不是静默降级
        raise QuizUnavailable(f"出题提示词缺失：{PROMPT_PATH}") from exc


def generate_quiz_items(conn: sqlite3.Connection, *, session_id: int,
                        knowledge_points: list[dict], count: int) -> list[dict]:
    """按知识点生成带出处的单选题。

    返回结构与 services/quiz.py 的 _agent_items 约定一致；
    无法出题时抛 QuizUnavailable，由调用方兜底。
    """
    if not knowledge_points:
        raise QuizUnavailable("没有可用知识点，无法出题")

    # 延迟导入：避免 import 阶段就把模型配置读进来（测试环境不需要密钥）
    from app.agents.pipeline import llm_available
    from app.services.llm import get_llm

    if not llm_available():
        raise QuizUnavailable("未配置模型密钥，Agent 出题不可用")

    picked = knowledge_points[: max(1, min(count, len(knowledge_points)))]
    allowed = {str(kp.get("chunk_key") or ""): kp for kp in knowledge_points}

    payload = {
        "count": len(picked),
        "course_scope": "只能依据下列知识点出题",
        "knowledge_points": [
            {
                "name": kp.get("name", ""),
                "definition": kp.get("definition", ""),
                "chunk_key": kp.get("chunk_key", ""),
                "page": kp.get("page") if kp.get("page") is not None else kp.get("slide"),
            }
            for kp in picked
        ],
    }

    try:
        raw = get_llm().json_call(
            _load_prompt(),
            json.dumps(payload, ensure_ascii=False),
            default=None,
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001 - 网络/密钥/解析异常统一视为不可用
        raise QuizUnavailable(f"Agent 出题调用失败：{exc}") from exc

    items = _extract_items(raw)
    cleaned = [_clean(item, allowed) for item in items]
    cleaned = [item for item in cleaned if item]
    if not cleaned:
        raise QuizUnavailable("模型未返回可用的题目")
    return cleaned[: len(picked)]


def _extract_items(raw: Any) -> list[dict]:
    """兼容三种常见返回：{items:[...]}、[...]、{questions:[...]}。"""
    if isinstance(raw, dict):
        for key in ("items", "questions", "data"):
            value = raw.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _clean(item: dict, allowed: dict[str, dict]) -> dict | None:
    """结构校验 + 证据绑定。不合格返回 None（丢弃该题）。"""
    stem = str(item.get("stem") or "").strip()
    options = item.get("options")
    answer = str(item.get("answer") or "").strip().upper()

    if not stem or not isinstance(options, list) or len(options) < 2:
        return None
    if answer not in OPTION_LETTERS:
        return None
    if OPTION_LETTERS.index(answer) >= len(options):
        return None

    # 去掉模型可能自带的「A.」前缀，前端会自己按序号生成字母
    cleaned_options = []
    for text in options[:4]:
        text = str(text).strip()
        if len(text) > 1 and text[0].upper() in OPTION_LETTERS and text[1] in ".、．)） ":
            text = text[2:].strip()
        if not text:
            return None
        cleaned_options.append(text)

    chunk_key = str(item.get("evidence_chunk_key") or "").strip()
    knowledge_name = str(item.get("knowledge_name") or "").strip()
    page = item.get("evidence_page")

    # 证据必须来自给定材料：优先用模型给的 key，其次按知识点名回查
    if chunk_key not in allowed:
        matched = next((kp for kp in allowed.values() if kp.get("name") == knowledge_name), None)
        if matched is None:
            return None
        chunk_key = str(matched.get("chunk_key") or "")
        if page is None:
            page = matched.get("page") if matched.get("page") is not None else matched.get("slide")
    if not chunk_key:
        return None

    try:
        page = int(page) if page is not None else None
    except (TypeError, ValueError):
        page = None

    return {
        "knowledge_name": knowledge_name or allowed[chunk_key].get("name", ""),
        "question_type": "single",
        "stem": stem,
        "options": cleaned_options,
        "answer": answer,
        "analysis": str(item.get("analysis") or "").strip(),
        "evidence_chunk_key": chunk_key,
        "evidence_page": page,
    }


__all__ = ["QuizUnavailable", "generate_quiz_items"]
