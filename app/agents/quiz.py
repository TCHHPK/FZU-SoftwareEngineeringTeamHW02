"""陈瑀涵：有证据的自测出题。返回值仅供服务端，包含标准答案。"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.db import repo_business as repo
from app.services.llm import get_llm
from app.services.query import quote_in_text

logger = logging.getLogger(__name__)


class QuizUnavailable(ValueError):
    """任务未完成或可核验的资料不足，调用方应终止组卷。"""


class QuizQuestion(BaseModel):
    seq: int = 0
    knowledge_name: str = Field(min_length=1)
    question_type: Literal["single", "judge"]
    stem: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(default_factory=list)
    answer: str
    analysis: str = Field(min_length=1)
    evidence_chunk_key: str = Field(min_length=1)
    evidence_page: int | None = None

    @model_validator(mode="after")
    def check_answer(self):
        if self.question_type == "single":
            if len(self.options) != 4 or len(set(self.options)) != 4:
                raise ValueError("单选必须有四个不同选项")
            if self.answer not in "ABCD" or len(self.answer) != 1:
                raise ValueError("单选答案必须为 A/B/C/D")
            if any(not option.strip() for option in self.options):
                raise ValueError("选项不得为空")
        elif self.options or self.answer not in {"对", "错"}:
            raise ValueError("判断题选项为空，答案为对或错")
        return self


def session_material(conn: sqlite3.Connection, session_id: int,
                     user_id: int) -> tuple[dict, list[dict]]:
    """只读取当前用户任务内、引文仍可回查的知识点；页码取原始分块。"""
    session = repo.get_session(conn, session_id)
    if not session or session["user_id"] != user_id:
        raise LookupError("任务不存在或无权访问")
    if session["status"] not in {"success", "partial"}:
        raise QuizUnavailable("请先完成笔记整理")
    doc_ids = set(session["doc_ids"])
    material, seen = [], set()
    for note in repo.list_notes(conn, session_id, content_type="note"):
        for item in repo.list_note_items(conn, note["note_id"]):
            if not item["name"].strip():
                continue
            for ev in item["evidence"]:
                chunk = conn.execute("SELECT * FROM chunks WHERE chunk_key = ?",
                                     (ev.get("chunk_key", ""),)).fetchone()
                if not chunk or chunk["doc_id"] not in doc_ids:
                    continue
                quote = str(ev.get("quote") or "")
                if not quote_in_text(quote, chunk["text"]):
                    continue
                identity = (item["name"], quote)
                if identity in seen:
                    break
                seen.add(identity)
                material.append({
                    "knowledge_name": item["name"], "quote": quote,
                    "chapter_title": chunk["chapter_title"] or note["chapter_title"],
                    "summary": item["definition"] or quote,
                    "evidence_chunk_key": chunk["chunk_key"],
                    "evidence_page": chunk["page_num"] or chunk["slide_index"],
                })
                break
    return session, material


def _templates(material: list[dict]) -> list[QuizQuestion]:
    questions = []
    for index, fact in enumerate(material):
        base = {key: fact[key] for key in
                ("knowledge_name", "evidence_chunk_key", "evidence_page")}
        # 只考查原文填空，不把其他知识点武断当作错误定义。
        quote = fact["quote"]
        name = fact["knowledge_name"]
        if name in quote:
            alternatives = list(dict.fromkeys(f["knowledge_name"] for f in material
                                             if f["knowledge_name"] != name))[:3]
            if len(alternatives) == 3:
                options = alternatives[:]
                position = index % 4
                options.insert(position, name)
                questions.append(QuizQuestion(**base, question_type="single",
                    stem="按课件原文填空：" + quote.replace(name, "____", 1),
                    options=options, answer="ABCD"[position],
                    analysis="原文：" + quote))
        questions.append(QuizQuestion(**base, question_type="judge",
            stem=f"判断下列文字是否与所引课件原文一致：{quote}", answer="对",
            analysis="原文：" + quote))
    # 优先覆盖不同知识点，再补充另一题型。
    return sorted(questions, key=lambda q: q.question_type != "single")


def generate_quiz(conn: sqlite3.Connection, session_id: int, user_id: int,
                  question_count: int = 5, scope_text: str = "", *,
                  use_llm: bool | None = None) -> list[QuizQuestion]:
    """供 app/services/quiz.py 调用；不写试卷表，不将答案公开到 API。

    scope_text 是知识点名或章节的子串筛选。资料不足不凑数，抛 QuizUnavailable。
    use_llm=False 强制模板；None 按密钥和 AGENT_STUB 自动选择。
    """
    if isinstance(question_count, bool) or not isinstance(question_count, int) or not 1 <= question_count <= 20:
        raise ValueError("question_count 必须是 1 到 20 的整数")
    _, material = session_material(conn, session_id, user_id)
    if scope_text.strip():
        material = [f for f in material if scope_text.strip() in
                    (f["knowledge_name"] + " " + f["chapter_title"])]
    if not material:
        raise QuizUnavailable("指定范围没有可核验的知识点")
    if use_llm is None:
        use_llm = os.getenv("AGENT_STUB", "0").lower() not in {"1", "true"} and bool(
            os.getenv("LLM_API_KEYS") or os.getenv("LLM_API_KEY"))
    questions: list[QuizQuestion] = []
    if use_llm:
        try:
            prompt = (Path(__file__).parent / "prompts" / "quiz.txt").read_text(encoding="utf-8")
            raw = get_llm().json_call(prompt, json.dumps({
                "question_count": question_count, "material": material[:40],
            }, ensure_ascii=False), default={})
            allowed = {(f["knowledge_name"], f["evidence_chunk_key"]): f for f in material}
            for entry in raw.get("items", []):
                try:
                    question = QuizQuestion.model_validate(entry)
                    source = allowed[(question.knowledge_name, question.evidence_chunk_key)]
                    question.evidence_page = source["evidence_page"]
                    questions.append(question)
                except (ValueError, KeyError, TypeError):
                    continue
        except Exception:
            logger.warning("模型出题失败，改用有原文证据的模板", exc_info=True)
    unique: dict[str, QuizQuestion] = {}
    for question in questions + _templates(material):
        unique.setdefault(question.stem.strip(), question)
    result = list(unique.values())[:question_count]
    if len(result) < question_count:
        raise QuizUnavailable(f"可核验题目仅 {len(result)} 道，无法生成 {question_count} 道；请补充知识点或减少题量")
    for seq, question in enumerate(result, 1):
        question.seq = seq
    return result
