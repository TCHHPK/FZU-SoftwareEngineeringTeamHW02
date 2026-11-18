"""FR-03 ~ FR-07：发起整理任务、查询进度、查看结果、导出、检索调试。

整理是长任务（几十秒到两分钟），因此：
  创建任务立即返回 session_id → 前端轮询 GET /api/sessions/{id} → 完成后取 GET /api/sessions/{id}/result。
后台执行使用 FastAPI BackgroundTasks，单机部署够用，不引入 Celery/Redis。
"""

from __future__ import annotations

import sqlite3
import traceback
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from app.agents import pipeline
from app.api.deps import CurrentUser, DbDep
from app.core.config import settings
from app.db import repo_business as repo
from app.db.conn import business_db
from app.schemas.api_io import (
    ChunkHit,
    Envelope,
    NoteItemOut,
    NoteView,
    SessionCreateRequest,
    SessionOut,
)
from app.services.query import search_chunks

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_RUNNABLE_PARSE_STATUS = {"success", "partial"}


def _session_out(row: dict) -> SessionOut:
    return SessionOut(
        session_id=row["session_id"],
        course_name=row.get("course_name") or "",
        source_file=row.get("source_file") or "",
        doc_ids=row.get("doc_ids") or [],
        task_type=row.get("task_type") or "note",
        status=row.get("status") or "pending",
        progress=row.get("progress") or 0,
        stage_message=row.get("stage_message") or "",
        error_message=row.get("error_message"),
        note_count=row.get("note_count") or 0,
        created_at=row.get("created_at") or "",
        finished_at=row.get("finished_at"),
    )


def _own_session(conn: sqlite3.Connection, session_id: int, user_id: int) -> dict:
    row = repo.get_session(conn, session_id)
    if not row or row["user_id"] != user_id:
        # 不区分「不存在」与「无权」，避免通过探测接口枚举他人任务
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    return row


def run_session_task(session_id: int) -> None:
    """后台任务入口：用独立数据库连接执行，异常一律落到 failed 状态。"""
    try:
        with business_db() as conn:
            repo.update_session(conn, session_id, status="running", progress=1,
                                stage_message="开始整理")
            session = repo.get_session(conn, session_id)
            if session and session.get("task_type") == "exam_scope":
                pipeline.build_exam_scope(conn, session_id, session.get("exam_scope") or "")
            else:
                pipeline.build_note(conn, session_id)
    except Exception as exc:  # noqa: BLE001 - 后台任务必须自己兜住所有异常
        detail = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        try:
            with business_db() as conn:
                repo.update_session(conn, session_id, status="failed", progress=100,
                                    stage_message="整理失败", error_message=detail[:500])
        except Exception:  # noqa: BLE001 - 连状态都写不进去时只能打印
            print(f"[fatal] 无法写入任务失败状态 session_id={session_id}")


@router.post("", response_model=Envelope, status_code=status.HTTP_202_ACCEPTED,
             summary="发起整理任务")
def create_session(payload: SessionCreateRequest, background: BackgroundTasks,
                   user: CurrentUser, conn: DbDep) -> Envelope:
    user_id = int(user["user_id"])

    docs = []
    for doc_id in payload.doc_ids:
        if not repo.user_can_access_doc(conn, doc_id, user_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"文档 {doc_id} 不存在或无权访问")
        row = repo.get_document(conn, doc_id)
        if row is None:  # pragma: no cover
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"文档 {doc_id} 不存在")
        if row["parse_status"] not in _RUNNABLE_PARSE_STATUS:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"《{row['source_file']}》当前状态为 {row['parse_status']}，无法整理："
                f"{row.get('parse_message') or '解析未成功'}")
        if repo.count_chunks(conn, doc_id) == 0:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"《{row['source_file']}》没有可用的文本内容")
        docs.append(row)

    course_name = (payload.course_name or "").strip() or docs[0]["course_name"]
    session_id = repo.create_session(
        conn, user_id=user_id, course_name=course_name,
        source_file="、".join(d["source_file"] for d in docs),
        doc_ids=[int(d["doc_id"]) for d in docs],
        task_type=payload.task_type, exam_scope=payload.exam_scope,
    )
    background.add_task(run_session_task, session_id)

    row = repo.get_session(conn, session_id) or {}
    return Envelope(message="任务已创建，正在处理", data=_session_out(row).model_dump())


@router.get("", response_model=Envelope, summary="历史整理记录")
def list_sessions(user: CurrentUser, conn: DbDep,
                  limit: int = Query(20, ge=1, le=100),
                  offset: int = Query(0, ge=0)) -> Envelope:
    rows = repo.list_sessions(conn, int(user["user_id"]), limit=limit, offset=offset)
    return Envelope(data=[_session_out(r).model_dump() for r in rows])


@router.get("/{session_id}", response_model=Envelope, summary="任务状态（前端轮询）")
def get_session(session_id: int, user: CurrentUser, conn: DbDep) -> Envelope:
    row = _own_session(conn, session_id, int(user["user_id"]))
    row["note_count"] = len(repo.list_notes(conn, session_id))
    return Envelope(data=_session_out(row).model_dump())


@router.get("/{session_id}/result", response_model=Envelope, summary="整理结果")
def get_result(session_id: int, user: CurrentUser, conn: DbDep) -> Envelope:
    row = _own_session(conn, session_id, int(user["user_id"]))
    if row["status"] in {"pending", "running"}:
        return Envelope(code=1, message="任务仍在处理中", data=_session_out(row).model_dump())
    if row["status"] == "failed":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            row.get("error_message") or "任务失败，没有可用结果")

    result = repo.session_result(conn, session_id)
    notes = repo.list_notes(conn, session_id)
    note = next((n for n in notes if n["content_type"] == "note"), None)
    items: list[NoteItemOut] = []
    if note:
        for it in repo.list_note_items(conn, note["note_id"]):
            items.append(NoteItemOut(**it))

    # 材料本身的告警来自文档解析记录；实现说明来自管线 notices
    warnings = [
        f"《{d['source_file']}》{d['parse_message']}"
        for d in repo.list_documents_by_ids(conn, row["doc_ids"] or [])
        if d.get("parse_status") == "partial" and d.get("parse_message")
    ]
    notices = list(getattr(result, "notices", []) or []) if result else []

    view = NoteView(
        session_id=session_id,
        course_name=row["course_name"],
        status=row["status"],
        outline=[{"title": n["chapter_title"], "content": n["content"]}
                 for n in notes if n["content_type"] == "note"],
        items=items,
        key_points=result.key_points if result else [],
        mindmap_text=result.mindmap_text if result else "",
        quality=result.quality if result else None,
        dropped_items=result.dropped_items if result else 0,
        warnings=warnings,
        notices=notices,
        result=None,
    )
    return Envelope(data=view.model_dump())


@router.get("/{session_id}/export", summary="导出笔记（Word / Markdown / LaTeX）")
def export_session(session_id: int, user: CurrentUser, conn: DbDep,
                   fmt: str = Query("md", pattern="^(md|markdown|tex|latex|docx|word)$")):
    row = _own_session(conn, session_id, int(user["user_id"]))
    result = repo.session_result(conn, session_id)
    if not result:
        raise HTTPException(status.HTTP_409_CONFLICT, "任务没有可导出的结果")

    stem = _safe_stem(row["course_name"] or "note")

    # Word：作业与报告都用 Word 交，最贴近真实使用场景
    if fmt in {"docx", "word"}:
        from app.services.export_docx import render_note_docx

        payload = render_note_docx(result, course_name=row["course_name"] or "")
        from fastapi import Response

        return Response(
            content=payload,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=_attachment_header(stem, "docx"),
        )

    if fmt in {"md", "markdown"}:
        body = _to_markdown(result)
        return PlainTextResponse(body, media_type="text/markdown; charset=utf-8",
                                 headers=_attachment_header(stem, "md"))
    body = _to_latex(result)
    return PlainTextResponse(body, media_type="application/x-tex; charset=utf-8",
                             headers=_attachment_header(stem, "tex"))


@router.get("/{session_id}/chunks/search", response_model=Envelope,
            summary="检索调试：看看证据是怎么被找出来的")
def search_session_chunks(session_id: int, user: CurrentUser, conn: DbDep,
                          q: str = Query(..., min_length=1),
                          top_k: int = Query(8, ge=1, le=30)) -> Envelope:
    row = _own_session(conn, session_id, int(user["user_id"]))
    found = search_chunks(conn, q, doc_ids=row["doc_ids"] or None, top_k=top_k)

    def dump(hits: list[dict]) -> list[dict]:
        return [ChunkHit(**{k: h.get(k) for k in ChunkHit.model_fields}).model_dump()
                for h in hits]

    return Envelope(data={
        "hits": dump(found.hits),
        "confident": dump(found.confident),
        "low_confidence": dump(found.low_confidence),
        # 前端据此显示「材料未涉及」而不是硬凑一个答案
        "insufficient": found.insufficient,
    })


# --------------------------------------------------------------------------
# 导出渲染
# --------------------------------------------------------------------------
def _safe_stem(name: str) -> str:
    keep = [ch for ch in name if ch.isalnum() or ch in "-_"]
    return ("".join(keep) or "note")[:40]


def _attachment_header(stem: str, ext: str) -> dict[str, str]:
    """构造下载头。

    HTTP 头只能是 latin-1，中文文件名必须同时给 ASCII 回退名和 RFC 5987 的 filename*，
    否则 Starlette 在编码响应头时会直接抛 UnicodeEncodeError。
    """
    ascii_name = "".join(ch for ch in stem if ch.isascii()) or "note"
    quoted = quote(f"{stem}.{ext}", safe="")
    return {"Content-Disposition":
            f"attachment; filename=\"{ascii_name}.{ext}\"; filename*=UTF-8''{quoted}"}


def _to_markdown(result) -> str:
    lines = [f"# {result.course_name or '课程笔记'}", ""]
    for node in result.outline:
        lines += [f"## {node.title}", ""]
        if node.summary:
            lines += [f"_{node.summary}_", ""]
        for item in node.items:
            lines.append(f"### {item.name}")
            if item.definition:
                lines += ["", item.definition]
            for point in item.key_points:
                lines.append(f"- {point}")
            if item.formula_latex:
                lines += ["", f"$$ {item.formula_latex} $$"]
            for ev in item.evidence:
                loc = []
                if ev.page_num:
                    loc.append(f"第 {ev.page_num} 页")
                if ev.slide_index:
                    loc.append(f"第 {ev.slide_index} 张幻灯片")
                lines += ["", f"> 【出处】{ev.chapter_title or node.title} {' '.join(loc)}"
                              f"（{ev.source_file} / {ev.chunk_key}）"]
            lines.append("")

    if result.key_points:
        lines += ["## 重点清单", ""] + [f"- {p}" for p in result.key_points] + [""]
    if result.mindmap_text:
        lines += ["## 知识结构", "", "```", result.mindmap_text, "```", ""]
    if result.quality:
        lines += ["## 整理质量自查（85% / 10% / 5%）", "",
                  f"- 总分：{result.quality.total}",
                  f"- 核心功能完成度：{result.quality.core}",
                  f"- 结构化与规范性：{result.quality.structure}",
                  f"- 拓展关联：{result.quality.extension}", ""]
        lines += [f"- {reason}" for reason in result.quality.reasons]
    if result.dropped_items:
        lines += ["", f"> 注：有 {result.dropped_items} 条内容因无法在原文中核验出处而被丢弃。"]
    return "\n".join(lines)


def _to_latex(result) -> str:
    """导出 LaTeX。

    刻意不使用 ctex 等中文宏包：不同环境安装情况不一致，宏包缺失会导致编译失败。
    正文采用单层文本，编译与排版在 Word/在线工具中完成。
    """
    def esc(text: str) -> str:
        for src, dst in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                         ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                         ("{", r"\{"), ("}", r"\}")):
            text = text.replace(src, dst)
        return text

    lines = [
        r"\documentclass[11pt]{article}",
        r"\usepackage{amsmath,amssymb}",
        r"\usepackage[margin=2.5cm]{geometry}",
        "",
        r"\title{" + esc(result.course_name or "课程笔记") + "}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        "",
    ]
    for node in result.outline:
        lines += [r"\section*{" + esc(node.title) + "}", ""]
        for item in node.items:
            lines.append(r"\subsection*{" + esc(item.name) + "}")
            if item.definition:
                lines += ["", esc(item.definition)]
            if item.formula_latex:
                lines += ["", r"\[ " + item.formula_latex + r" \]"]
            for ev in item.evidence:
                loc = []
                if ev.page_num:
                    loc.append(f"P{ev.page_num}")
                if ev.slide_index:
                    loc.append(f"Slide {ev.slide_index}")
                lines += ["", r"\begin{quote}\small [" + esc(
                    " ".join(loc) + " " + ev.source_file + " " + ev.chunk_key) + r"]\end{quote}"]
            lines.append("")

    if result.key_points:
        lines += [r"\section*{Key Points}", r"\begin{itemize}"]
        lines += [r"  \item " + esc(p) for p in result.key_points]
        lines += [r"\end{itemize}", ""]
    if result.mindmap_text:
        lines += [r"\section*{Knowledge Structure}", r"\begin{verbatim}",
                  result.mindmap_text, r"\end{verbatim}", ""]
    lines += [r"\end{document}", ""]
    return "\n".join(lines)
