"""v1.3.0（Beta）K1 / K2 / K3 接口：复习包、冲刺计划、出处原文。

四个端点（契约 3.1 / 3.2 / 3.3 / 3.5，主责均为沈文驰）：
    POST /api/sessions/{session_id}/review-pack   生成复习包
    GET  /api/review-packs/{pack_id}/export       导出复习包（docx）
    POST /api/sessions/{session_id}/review-plan   考前冲刺计划
    GET  /api/chunks/{chunk_key}                  出处原文（抽屉取数）

本文件由 router.py 可选导入：文件到位后重启即自动挂载，不需要改路由汇总。
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import CurrentUser, DbDep
from app.core.config import settings
from app.db.repo_business import user_can_access_doc
from app.schemas.api_io import ChunkDetailOut, Envelope, ReviewPackRequest, ReviewPlanRequest
from app.services import review_pack, review_plan

router = APIRouter(prefix="/api", tags=["review"])

_DOCX_MEDIA_TYPE = ("application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document")


# --------------------------------------------------------------------------
# K1 复习包
# --------------------------------------------------------------------------
@router.post("/sessions/{session_id}/review-pack", response_model=Envelope,
             summary="生成复习包（K1：五章聚合，返回 pack_id）")
def create_review_pack(session_id: int, user: CurrentUser, conn: DbDep,
                       payload: ReviewPackRequest | None = None) -> Envelope:
    if not settings.enable_review_pack:
        raise HTTPException(404, "复习包功能未开启")
    try:
        data = review_pack.build(
            conn,
            user_id=int(user["user_id"]),
            session_id=int(session_id),
            include_mindmap=True if payload is None else payload.include_mindmap,
        )
    except review_pack.ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return Envelope(message="复习包已生成", data=data)


@router.get("/review-packs/{pack_id}/export",
            summary="导出复习包（K1：当前只支持 docx）")
def export_review_pack(pack_id: int, user: CurrentUser, conn: DbDep,
                       fmt: str = Query("docx", description="目前只支持 docx")) -> Response:
    if not settings.enable_review_pack:
        raise HTTPException(404, "复习包功能未开启")
    try:
        content, filename = review_pack.export(
            conn, pack_id=int(pack_id), user_id=int(user["user_id"]), fmt=fmt)
    except review_pack.ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return Response(content=content, media_type=_DOCX_MEDIA_TYPE,
                    headers=_attachment_header(filename))


def _attachment_header(filename: str) -> dict[str, str]:
    """中文文件名必须同时给 ASCII 回退名和 RFC 5987 的 filename*。

    HTTP 头只能是 latin-1，只写中文会让 Starlette 编码响应头时直接抛
    UnicodeEncodeError（导出接口因此 500 过一次）。
    """
    stem, _, ext = filename.rpartition(".")
    ascii_name = "".join(ch for ch in stem if ch.isascii()) or "review-pack"
    quoted = quote(filename, safe="")
    return {"Content-Disposition":
            f"attachment; filename=\"{ascii_name}.{ext or 'docx'}\"; filename*=UTF-8''{quoted}"}


# --------------------------------------------------------------------------
# K2 考前冲刺计划
# --------------------------------------------------------------------------
@router.post("/sessions/{session_id}/review-plan", response_model=Envelope,
             summary="考前冲刺计划（K2）")
def create_review_plan(session_id: int, payload: ReviewPlanRequest,
                       user: CurrentUser, conn: DbDep) -> Envelope:
    if not settings.enable_review_plan:
        raise HTTPException(404, "冲刺计划功能未开启")
    try:
        data = review_plan.build_plan(
            conn,
            user_id=int(user["user_id"]),
            session_id=int(session_id),
            exam_date=payload.exam_date,
            daily_minutes=payload.daily_minutes,
        )
    except review_plan.PlanError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return Envelope(message="计划已生成", data=data)


# --------------------------------------------------------------------------
# K3 出处原文（前端 EvidenceDrawer 取数）
# --------------------------------------------------------------------------
@router.get("/chunks/{chunk_key}", response_model=Envelope,
            summary="出处原文（K3：含前后文，越权一律 404）")
def get_chunk(chunk_key: str, user: CurrentUser, conn: DbDep) -> Envelope:
    # 鉴权必须三步：按 key 取 chunks → doc_id 反查 documents → user_can_access_doc。
    # 禁止只按 chunk_key 直出内容，否则可以枚举他人材料（C3 裁决）。
    row = conn.execute(
        "SELECT chunk_key, doc_id, seq, page_num, text FROM chunks WHERE chunk_key = ?",
        (chunk_key,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "出处不存在")
    doc_id = int(row["doc_id"])
    if not user_can_access_doc(conn, doc_id, int(user["user_id"])):
        raise HTTPException(404, "出处不存在")

    document = conn.execute(
        "SELECT source_file FROM documents WHERE doc_id = ?", (doc_id,),
    ).fetchone()
    if document is None:  # 外键约束下不应出现，防御一次脏数据
        raise HTTPException(404, "出处不存在")

    before = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ? AND seq < ? ORDER BY seq DESC LIMIT 1",
        (doc_id, int(row["seq"])),
    ).fetchone()
    after = conn.execute(
        "SELECT text FROM chunks WHERE doc_id = ? AND seq > ? ORDER BY seq ASC LIMIT 1",
        (doc_id, int(row["seq"])),
    ).fetchone()

    data = ChunkDetailOut(
        chunk_key=row["chunk_key"],
        text=row["text"] or "",
        page_num=row["page_num"],
        before=(before["text"] or "") if before is not None else "",
        after=(after["text"] or "") if after is not None else "",
        source_file=document["source_file"] or "",
    )
    return Envelope(data=data.model_dump())
