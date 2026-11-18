"""FR-08 / FR-09：管理员维护公共资料与测试记录。

权限：仅 role=admin。公共资料（is_public=1）对所有学生可见，是领域知识库的课件来源。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.deps import AdminUser, DbDep
from app.api.routes_uploads import _save_upload, to_document_out
from app.core.config import settings
from app.db import repo_business as repo
from app.schemas.api_io import Envelope
from app.services.ingest import ingest_document

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/materials", response_model=Envelope, summary="上传公共课件（入领域资料）")
async def upload_public_material(file: UploadFile = File(...), course_name: str = Form(""),
                                 user: AdminUser = None,  # type: ignore[assignment]
                                 conn: DbDep = None) -> Envelope:  # type: ignore[assignment]
    if user is None or conn is None:  # pragma: no cover
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "需要管理员权限")

    stored, _size = await _save_upload(file, user_id=int(user["user_id"]))
    fallback_course = Path(file.filename or "").stem.strip()
    result = ingest_document(
        conn, stored,
        user_id=int(user["user_id"]),
        course_name=(course_name or "").strip() or fallback_course,
        stored_path=str(stored),
        display_name=file.filename or "",
        is_public=True,
    )
    row = repo.get_document(conn, result["doc_id"])
    if row is None:  # pragma: no cover
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "文档记录写入失败")
    if result["parse_status"] == "failed":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            result.get("message") or "解析失败")

    return Envelope(message="公共资料已入库", data={
        "document": to_document_out(conn, row, chunk_count=result.get("chunks") or 0).model_dump(),
        "warnings": result.get("warnings") or [],
        "chapters": result.get("chapters") or [],
    })


@router.get("/materials", response_model=Envelope, summary="公共资料列表")
def list_public_materials(user: AdminUser, conn: DbDep) -> Envelope:
    rows = [r for r in repo.list_documents(conn, int(user["user_id"])) if r.get("is_public")]
    return Envelope(data=[to_document_out(conn, r).model_dump() for r in rows])


@router.get("/stats", response_model=Envelope, summary="运行概况（答辩时可用来展示系统用量）")
def stats(user: AdminUser, conn: DbDep) -> Envelope:
    def one(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return Envelope(data={
        "users": one("SELECT COUNT(*) FROM users"),
        "documents": one("SELECT COUNT(*) FROM documents"),
        "public_documents": one("SELECT COUNT(*) FROM documents WHERE is_public = 1"),
        "chunks": one("SELECT COUNT(*) FROM chunks"),
        "sessions": one("SELECT COUNT(*) FROM sessions"),
        "sessions_failed": one("SELECT COUNT(*) FROM sessions WHERE status = 'failed'"),
        "notes": one("SELECT COUNT(*) FROM notes"),
        "note_items": one("SELECT COUNT(*) FROM note_items"),
        "chats": one("SELECT COUNT(*) FROM chats"),
        "features": settings.features(),
    })


@router.get("/compare-records", response_model=Envelope,
            summary="FR-09 定制效果对比记录（由 scripts/eval_agent.py 写入）")
def compare_records(user: AdminUser, conn: DbDep) -> Envelope:
    """评测结果以 JSON 文件落盘（scripts/eval_agent.py 产出），这里只做读取转发。

    没有文件时返回空列表，不伪造数据。
    """
    import json

    path = settings.storage_dir / "eval" / "compare.json"
    if not path.exists():
        return Envelope(message="还没有评测记录，请先运行 scripts/eval_agent.py", data=[])
    try:
        return Envelope(data=json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"评测记录文件损坏：{exc}") from exc
