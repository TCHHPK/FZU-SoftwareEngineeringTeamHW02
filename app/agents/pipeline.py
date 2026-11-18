"""Agent 管线。

外层接口已经定稿（build_note / answer_question / build_examples / build_exam_scope），
API 与前端按这些签名对接。**内部实现分两个阶段交付**：

  阶段一（当前）：use_stub=True 或未配置 LLM_API_KEYS 时走 `stub_note()`。
    它以真实解析出的 chunk 为输入、带真实出处，足以驱动前端联调与验收用例走查，
    但知识点是「按段落截断」而不是模型抽取的，因此**不得作为答辩演示结果**。
  阶段二（陈瑀涵）：实现 build_note 的完整管线：
    逐块抽取 → 证据校验 → 归并去重 → 检索补全 → 生成三件套 → 加权自评。
    伪代码见《编程组执行方案》3.4 节。

约定：
  * 任何单块失败都不能让整单任务失败，记 progress.stage_message 与 warnings 后继续；
  * 所有写入 notes 的内容必须能追到 chunk_key；
  * 不在这里写 SQL，落库统一走 app/db/repo_business.py。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.core.config import settings
from app.db import repo_business as repo
from app.schemas.agent_io import (
    AnswerResult,
    Evidence,
    ExamScopeResult,
    ExampleResult,
    KnowledgeItem,
    NoteResult,
    OutlineNode,
    QualityScore,
)
from app.services.llm import LLMError, get_llm
from app.services.query import normalize_text, quote_in_text, search_chunks

logger = logging.getLogger("app.pipeline")
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

# 分块正文里超过该长度就截断进笔记（stub 用；真实管线由模型决定粒度）
STUB_ITEM_MAX_CHARS = 160


class PipelineNotConfigured(RuntimeError):
    """未配置模型服务且未开启 stub 时抛出，路由层据此返回可读的失败原因。"""


@dataclass
class ProgressReporter:
    """任务进度上报。路由层把 session_id 传进来，管线只负责报数。"""

    conn: sqlite3.Connection
    session_id: int
    on_update: Callable[[int, str], None] | None = None
    _last: int = field(default=0, init=False)

    def report(self, progress: int, message: str) -> None:
        progress = max(0, min(100, int(progress)))
        self._last = progress
        repo.update_session(self.conn, self.session_id, status="running",
                            progress=progress, stage_message=message)
        if self.on_update:
            self.on_update(progress, message)


def llm_available() -> bool:
    return bool(os.getenv("LLM_API_KEYS") or os.getenv("LLM_API_KEY"))


def use_stub() -> bool:
    """是否使用占位实现：显式开启，或根本没配模型服务时自动降级（便于本地联调）。"""
    if os.getenv("AGENT_STUB", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return not llm_available()


# --------------------------------------------------------------------------
# 主流程：整理笔记
# --------------------------------------------------------------------------
def build_note(conn: sqlite3.Connection, session_id: int) -> NoteResult:
    session = repo.get_session(conn, session_id)
    if not session:
        raise ValueError(f"任务不存在：{session_id}")

    progress = ProgressReporter(conn, session_id)
    progress.report(5, "读取材料分块")

    doc_ids: list[int] = session["doc_ids"]
    chunks: list[dict] = []
    for doc_id in doc_ids:
        chunks.extend(_doc_chunks(conn, doc_id))
    if not chunks:
        raise ValueError("所选材料没有可用的文本分块，请确认课件是否解析成功")

    if use_stub():
        result = stub_note(chunks, course_name=session["course_name"], progress=progress)
        result.notices.append("当前为占位实现（未配置模型服务），结果仅供联调，请勿用于演示")
    else:
        result = run_note_pipeline(conn, session, chunks, progress=progress)

    _persist_result(conn, session, result)
    # 只有材料/结果本身的问题才判为「部分成功」；实现说明（notices）不影响状态
    final_status = "partial" if result.warnings else "success"
    repo.update_session(conn, session_id, status=final_status, progress=100,
                        stage_message="整理完成" if final_status == "success" else "整理完成（有告警）")
    return result


def run_note_pipeline(conn: sqlite3.Connection, session: dict, chunks: list[dict], *,
                      progress: ProgressReporter) -> NoteResult:
    """真实管线：逐块抽取、证据校验、去重、检索补全、渲染与自评。

    步骤：
      1. 逐块调用 prompts/extract.txt，拿到 KnowledgeItem 列表（map，保证覆盖全部内容）；
      2. verifier.bind_and_filter：丢弃 chunk_key 不存在或 quote 不在原文的条目；
      3. 按知识点名称归一化去重（reduce）；
      4. retriever 检索公共知识库补定义/前置/关联；
      5. 调用 prompts/render_note.txt 生成结构化笔记 + 重点清单 + 文本导图；
      6. enable_quality_eval 时调用 prompts/self_eval.txt 做 85/10/5 加权自评。
    """
    if not llm_available():
        raise PipelineNotConfigured("未配置模型密钥，无法运行真实 Agent 管线")

    llm = get_llm()
    course_name = (session.get("course_name") or "").strip()
    warnings: list[str] = []
    extracted: list[KnowledgeItem] = []
    dropped = 0

    extract_system = _load_prompt("extract.txt")
    total = max(len(chunks), 1)
    for index, chunk in enumerate(chunks, start=1):
        progress.report(10 + int(35 * index / total),
                        f"抽取知识点 {index}/{len(chunks)}")
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        payload = {
            "course_name": course_name,
            "chapter_title": chunk.get("chapter_title") or "",
            "section_title": chunk.get("section_title") or "",
            "page_num": chunk.get("page_num"),
            "slide_index": chunk.get("slide_index"),
            "chunk_key": chunk.get("chunk_key"),
            "text": text,
        }
        try:
            raw = llm.json_call(extract_system, json.dumps(payload, ensure_ascii=False),
                                default={"items": []})
            records = raw.get("items", []) if isinstance(raw, dict) else []
            if not isinstance(records, list):
                raise ValueError("items 不是数组")
            for record in records:
                item = _bind_extracted_item(record, chunk)
                if item is None:
                    dropped += 1
                else:
                    extracted.append(item)
        except Exception as exc:  # 单块失败不拖垮整个任务
            logger.warning("分块 %s 抽取失败：%s", chunk.get("chunk_key"), exc)
            warnings.append(f"分块 {chunk.get('chunk_key', '?')} 抽取失败，已跳过")

    progress.report(50, "归并重复知识点")
    items = _deduplicate_items(extracted)
    if not items:
        raise ValueError("没有抽取到可核验的知识点，请检查课件文本或模型配置")

    progress.report(58, "检索可见领域资料补全知识关联")
    _supplement_from_retrieval(conn, session, items)

    progress.report(68, "生成结构化笔记、重点与思维导图")
    outline = _build_outline(items)
    try:
        render_data = _render_outputs(llm, course_name, outline)
    except LLMError as exc:
        logger.warning("笔记渲染模型调用失败，使用确定性降级输出：%s", exc)
        warnings.append("笔记编辑阶段模型调用失败，已使用已核验知识点生成降级结果")
        render_data = {}
    _apply_chapter_summaries(outline, render_data.get("chapter_summaries"))
    key_points = _clean_string_list(render_data.get("key_points"))
    if not key_points:
        key_points = [item.name for item in sorted(
            items, key=lambda it: it.importance, reverse=True)[:15]]
    mindmap = str(render_data.get("mindmap_text") or "").strip()
    if not mindmap:
        mindmap = _fallback_mindmap(course_name, outline)

    quality = None
    if settings.enable_quality_eval:
        progress.report(84, "按 85%/10%/5% 进行质量自评")
        quality = _evaluate_quality(llm, outline, key_points, mindmap,
                                    dropped=dropped, extracted=len(extracted))

    progress.report(94, "Agent 结果已生成，准备落库")
    return NoteResult(
        course_name=course_name,
        outline=outline,
        key_points=key_points,
        mindmap_text=mindmap,
        quality=quality,
        dropped_items=dropped,
        warnings=warnings,
    )


def _load_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if not path.exists():
        raise PipelineNotConfigured(f"缺少提示词文件：{name}")
    return path.read_text(encoding="utf-8").strip()


def _bind_extracted_item(record: object, chunk: dict) -> KnowledgeItem | None:
    """将模型条目绑定到当前分块；只有逐字可回查的引文才会被保留。"""
    if not isinstance(record, dict):
        return None
    name = str(record.get("name") or "").strip()
    quote = str(record.get("quote") or "").strip()
    if not quote:
        evidences = record.get("evidence") or []
        if isinstance(evidences, list) and evidences and isinstance(evidences[0], dict):
            quote = str(evidences[0].get("quote") or "").strip()
    if not name or not quote_in_text(quote, str(chunk.get("text") or "")):
        return None

    points = _clean_string_list(record.get("key_points"))
    try:
        importance = max(1, min(5, int(record.get("importance") or 3)))
    except (TypeError, ValueError):
        importance = 3
    formula = str(record.get("formula_latex") or "").strip() or None
    return KnowledgeItem(
        name=name[:120],
        definition=str(record.get("definition") or "").strip(),
        key_points=points[:8],
        formula_latex=formula,
        importance=importance,
        evidence=[Evidence(
            chunk_key=str(chunk.get("chunk_key") or ""),
            source_file=str(chunk.get("source_file") or ""),
            chapter_title=str(chunk.get("chapter_title") or ""),
            page_num=chunk.get("page_num"),
            slide_index=chunk.get("slide_index"),
            quote=quote[:160],
        )],
        verified=True,
    )


def _item_key(name: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", normalize_text(name))


def _deduplicate_items(items: list[KnowledgeItem]) -> list[KnowledgeItem]:
    merged: dict[str, KnowledgeItem] = {}
    for item in items:
        key = _item_key(item.name)
        if not key:
            continue
        old = merged.get(key)
        if old is None:
            merged[key] = item.model_copy(deep=True)
            continue
        if len(item.definition) > len(old.definition):
            old.definition = item.definition
        old.key_points = list(dict.fromkeys(old.key_points + item.key_points))[:10]
        old.importance = max(old.importance, item.importance)
        if not old.formula_latex and item.formula_latex:
            old.formula_latex = item.formula_latex
        seen = {(e.chunk_key, e.quote) for e in old.evidence}
        old.evidence.extend(e for e in item.evidence if (e.chunk_key, e.quote) not in seen)
    return list(merged.values())


def _supplement_from_retrieval(conn: sqlite3.Connection, session: dict,
                               items: list[KnowledgeItem]) -> None:
    """从当前用户可见且同课程的公共资料补充关联，但不引入无证据的新结论。"""
    visible = repo.list_documents(conn, int(session["user_id"]), include_public=True)
    public_ids = [int(d["doc_id"]) for d in visible
                  if d.get("is_public") and
                  (not session.get("course_name") or d.get("course_name") == session.get("course_name"))]
    if not public_ids:
        return
    for item in items:
        found = search_chunks(conn, item.name, doc_ids=public_ids, top_k=2)
        for hit in found.confident:
            ev = _hit_evidence(hit)
            if quote_in_text(ev.quote, str(hit.get("text") or "")) and all(
                    old.chunk_key != ev.chunk_key for old in item.evidence):
                item.evidence.append(ev)
                excerpt = re.split(r"[。！？\n]", str(hit.get("text") or "").strip())[0].strip()
                if len(excerpt) >= 5:
                    point = f"相关资料：{excerpt[:120]}"
                    if point not in item.key_points:
                        item.key_points.append(point)


def _build_outline(items: list[KnowledgeItem]) -> list[OutlineNode]:
    grouped: dict[str, list[KnowledgeItem]] = {}
    for item in items:
        chapter = next((e.chapter_title for e in item.evidence if e.chapter_title), "未标注章节")
        grouped.setdefault(chapter, []).append(item)
    return [OutlineNode(title=chapter, level=1, items=chapter_items)
            for chapter, chapter_items in grouped.items()]


def _render_outputs(llm, course_name: str, outline: list[OutlineNode]) -> dict:
    compact = {
        "course_name": course_name,
        "chapters": [{
            "title": node.title,
            "items": [{"name": it.name, "definition": it.definition,
                       "key_points": it.key_points, "importance": it.importance}
                      for it in node.items],
        } for node in outline],
    }
    raw = llm.json_call(_load_prompt("render_note.txt"),
                        json.dumps(compact, ensure_ascii=False), default={})
    return raw if isinstance(raw, dict) else {}


def _apply_chapter_summaries(outline: list[OutlineNode], raw: object) -> None:
    if not isinstance(raw, list):
        return
    summaries = {str(row.get("title") or ""): str(row.get("summary") or "").strip()
                 for row in raw if isinstance(row, dict)}
    for node in outline:
        node.summary = summaries.get(node.title, "")


def _clean_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(x).strip() for x in value if str(x).strip()))


def _fallback_mindmap(course_name: str, outline: list[OutlineNode]) -> str:
    lines = [course_name or "课程笔记"]
    for chapter_index, node in enumerate(outline):
        chapter_branch = "└─" if chapter_index == len(outline) - 1 else "├─"
        lines.append(f"{chapter_branch} {node.title}")
        for item_index, item in enumerate(node.items):
            item_branch = "└─" if item_index == len(node.items) - 1 else "├─"
            lines.append(f"   {item_branch} {item.name}")
    return "\n".join(lines)


def _evaluate_quality(llm, outline: list[OutlineNode], key_points: list[str],
                      mindmap: str, *, dropped: int, extracted: int) -> QualityScore:
    payload = {
        "chapters": [{"title": n.title, "item_names": [i.name for i in n.items]}
                     for n in outline],
        "key_points": key_points,
        "mindmap_text": mindmap,
        "verified_items": sum(len(n.items) for n in outline),
        "dropped_items": dropped,
    }
    try:
        raw = llm.json_call(_load_prompt("self_eval.txt"),
                            json.dumps(payload, ensure_ascii=False), default={})
    except LLMError as exc:
        logger.warning("质量自评模型调用失败，使用程序指标：%s", exc)
        raw = {}
    if isinstance(raw, dict):
        try:
            clamp = lambda value: max(0.0, min(100.0, float(value)))
            return QualityScore.from_dimensions(
                core=clamp(raw.get("core", 0)),
                structure=clamp(raw.get("structure", 0)),
                extension=clamp(raw.get("extension", 0)),
                reasons=_clean_string_list(raw.get("reasons")),
            )
        except (TypeError, ValueError):
            pass
    verified = sum(len(n.items) for n in outline)
    denom = max(extracted + dropped, 1)
    core = round(verified / denom * 100, 1)
    structure = 90.0 if outline and key_points and mindmap else 60.0
    extension = 70.0 if len(outline) > 1 else 50.0
    return QualityScore.from_dimensions(
        core=core, structure=structure, extension=extension,
        reasons=["模型自评不可用，已使用可核验的程序指标降级评分"],
    )


def stub_note(chunks: list[dict], *, course_name: str, progress: ProgressReporter) -> NoteResult:
    """占位实现：把分块按章节聚合成可用结构，出处真实，知识点为原文截断。

    存在的意义：让前端、导出、历史、评测框架在模型接入之前就能真跑通。
    """
    progress.report(40, "按章节聚合分块（占位实现）")
    grouped: dict[str, list[dict]] = {}
    for chunk in chunks:
        key = chunk.get("chapter_title") or "未标注章节"
        grouped.setdefault(key, []).append(chunk)

    outline: list[OutlineNode] = []
    key_points: list[str] = []
    for idx, (chapter, group) in enumerate(grouped.items(), start=1):
        items: list[KnowledgeItem] = []
        for chunk in group:
            text = (chunk.get("text") or "").strip()
            if not text:
                continue
            first_line = text.split("\n")[0].strip()
            section = (chunk.get("section_title") or "").strip()
            name = f"{section}｜{first_line[:20]}" if section else (first_line[:24] or "")
            items.append(KnowledgeItem(
                name=name or f"片段 {chunk['chunk_key']}",
                definition=text[:STUB_ITEM_MAX_CHARS],
                key_points=[],
                evidence=[Evidence(
                    chunk_key=chunk["chunk_key"],
                    source_file=chunk.get("source_file", ""),
                    chapter_title=chapter,
                    page_num=chunk.get("page_num"),
                    slide_index=chunk.get("slide_index"),
                    quote=text[:80],
                )],
                verified=True,      # 出处直接来自分块本身，必然可核验
            ))
        outline.append(OutlineNode(title=chapter, level=1, summary=f"共 {len(items)} 个片段",
                                   items=items))
        key_points.append(f"{chapter}（{len(items)} 个片段，占位实现未做重点判断）")
        progress.report(40 + int(40 * idx / max(len(grouped), 1)), f"聚合章节：{chapter}")

    progress.report(90, "生成文本版思维导图（占位实现）")
    mindmap = "\n".join(
        [course_name or "课程笔记"] +
        [f"{'├─' if i < len(outline) - 1 else '└─'} {node.title}" for i, node in enumerate(outline)]
    )

    quality = None
    if settings.enable_quality_eval:
        # 占位评分：只反映「有出处」这一件事，不假装评了内容质量
        with_evidence = sum(1 for node in outline for it in node.items if it.evidence)
        total_items = sum(len(node.items) for node in outline) or 1
        coverage = with_evidence / total_items * 100
        quality = QualityScore.from_dimensions(
            core=round(coverage, 1), structure=70.0, extension=50.0,
            reasons=["占位实现：core 仅统计「条目是否有原文出处」，未评估知识点完整性"],
        )

    return NoteResult(course_name=course_name, outline=outline, key_points=key_points,
                      mindmap_text=mindmap, quality=quality, dropped_items=0)


# --------------------------------------------------------------------------
# 问答
# --------------------------------------------------------------------------
def answer_question(conn: sqlite3.Connection, *, question: str, doc_ids: list[int],
                    course_name: str = "") -> AnswerResult:
    """FR-05：只用检索到的证据回答，证据不足时明确说明。

    检索为空或全部 low_confidence 时直接返回 insufficient=True，不交给模型自由发挥。
    """
    found = search_chunks(conn, question, doc_ids=doc_ids or None, top_k=6)

    # 三态判定，顺序不能换：
    #   1) 一条都没召回        → 明确「未涉及」
    #   2) 只有低置信片段      → 明确「依据不足」，不交给模型自由发挥
    #   3) 有可信片段            → 仅把这些片段交给模型作答
    if found.empty:
        return AnswerResult(answer="该内容在所选材料中未涉及，无法回答。", evidence=[],
                            insufficient=True)

    if found.insufficient:
        return AnswerResult(
            answer="检索到的片段与问题的相关度较低，材料依据不足，建议换一种问法或补充材料。",
            evidence=[_hit_evidence(h) for h in found.low_confidence[:3]], insufficient=True)

    if not llm_available():
        raise PipelineNotConfigured("检索已完成，但未配置模型密钥，无法生成答案")

    evidence_rows = found.confident[:6]
    evidence_payload = [{
        "chunk_key": h.get("chunk_key"),
        "chapter_title": h.get("chapter_title"),
        "page_num": h.get("page_num"),
        "slide_index": h.get("slide_index"),
        "text": h.get("text"),
    } for h in evidence_rows]
    raw = get_llm().json_call(
        _load_prompt("qa.txt"),
        json.dumps({"course_name": course_name, "question": question,
                    "evidence": evidence_payload}, ensure_ascii=False),
        default=None,
    )
    if not isinstance(raw, dict) or not str(raw.get("answer") or "").strip():
        raise LLMError("问答模型未返回有效答案")

    allowed = {str(h.get("chunk_key")): h for h in evidence_rows}
    cited = raw.get("citations") or []
    cited_keys = [str(x) for x in cited if str(x) in allowed]
    if not cited_keys:
        return AnswerResult(
            answer="模型未能给出可核验的材料引用，本次回答已拦截，请重试或换一种问法。",
            evidence=[], insufficient=True)
    evidence = [_hit_evidence(allowed[key]) for key in cited_keys[:3]]
    return AnswerResult(answer=str(raw["answer"]).strip(), evidence=evidence, insufficient=False)


# --------------------------------------------------------------------------
# 可选功能
# --------------------------------------------------------------------------
def build_examples(conn: sqlite3.Connection, session_id: int) -> ExampleResult:
    """OP-01：例题检索优先、生成兜底。TODO（陈瑀涵）。"""
    raise PipelineNotConfigured("例题整理尚未实现（OP-01）")


def build_exam_scope(conn: sqlite3.Connection, session_id: int, scope_text: str) -> ExamScopeResult:
    """OP-05：按考试范围筛选复习笔记。TODO（陈瑀涵）。"""
    raise PipelineNotConfigured("考试范围复习尚未实现（OP-05）")


# --------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------
def _doc_chunks(conn: sqlite3.Connection, doc_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT c.chunk_key, c.text, c.chapter_title, c.section_title,
                  c.page_num, c.slide_index, d.source_file
           FROM chunks c JOIN documents d ON d.doc_id = c.doc_id
           WHERE c.doc_id = ? ORDER BY c.seq""", (doc_id,)).fetchall()
    return [dict(r) for r in rows]


def _hit_evidence(hit: dict) -> Evidence:
    return Evidence(
        chunk_key=hit.get("chunk_key", ""),
        source_file=hit.get("source_file", ""),
        chapter_title=hit.get("chapter_title", ""),
        page_num=hit.get("page_num"),
        slide_index=hit.get("slide_index"),
        quote=(hit.get("text") or "")[:80],
    )


def _persist_result(conn: sqlite3.Connection, session: dict, result: NoteResult) -> None:
    """把 NoteResult 拆成 notes（三种 content_type）+ note_items 落库。"""
    user_id = session["user_id"]
    session_id = session["session_id"]
    course_name = result.course_name or session["course_name"]

    for node in result.outline:
        content = _render_markdown(node)
        note_id = repo.save_note(conn, user_id=user_id, session_id=session_id,
                                 course_name=course_name, content_type="note",
                                 content=content, chapter_title=node.title,
                                 quality=result.quality, dropped_items=result.dropped_items)
        repo.save_note_items(conn, note_id, [it.model_dump() for it in node.items])

    if result.key_points:
        repo.save_note(conn, user_id=user_id, session_id=session_id, course_name=course_name,
                       content_type="key_points", content="\n".join(result.key_points))
    if result.mindmap_text:
        repo.save_note(conn, user_id=user_id, session_id=session_id, course_name=course_name,
                       content_type="mindmap", content=result.mindmap_text)


def _render_markdown(node: OutlineNode) -> str:
    lines = [f"## {node.title}"]
    if node.summary:
        lines.append(f"_{node.summary}_")
    for item in node.items:
        lines.append(f"### {item.name}")
        if item.definition:
            lines.append(item.definition)
        for point in item.key_points:
            lines.append(f"- {point}")
        if item.formula_latex:
            lines.append(f"$$ {item.formula_latex} $$")
        for ev in item.evidence:
            location = []
            if ev.page_num:
                location.append(f"第 {ev.page_num} 页")
            if ev.slide_index:
                location.append(f"第 {ev.slide_index} 张幻灯片")
            lines.append(f"> 【出处】《{node.title}》{' '.join(location)}"
                         f"（{ev.source_file} / {ev.chunk_key}）")
    return "\n".join(lines)
