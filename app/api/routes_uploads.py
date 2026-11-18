"""FR-02：课件上传与解析。

上传流程：校验扩展名 → 校验大小 → 落盘（文件名用内容哈希，避免路径穿越与重名）
→ 解析入库 → 返回解析状态与告警。

注意：解析失败也要落一条 documents 记录（parse_status=failed），
这样前端能展示"为什么失败"，而不是只看到一个 500。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.deps import CurrentUser, DbDep
from app.core.config import settings
from app.db import repo_business as repo
from app.schemas.api_io import DocumentOut, Envelope, UploadOut
from app.services.ingest import ingest_document

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

_CHUNK = 1024 * 1024
# 响应里回显章节太多没意义，前端只需要知道识别到了哪些章
_MAX_CHAPTERS_IN_RESPONSE = 50


def to_document_out(conn, row: dict, *, chunk_count: int | None = None) -> DocumentOut:
    return DocumentOut(
        doc_id=row["doc_id"],
        course_name=row.get("course_name") or "",
        source_file=row.get("source_file") or "",
        file_type=row.get("file_type") or "",
        page_count=row.get("page_count") or 0,
        text_chars=row.get("text_chars") or 0,
        is_public=bool(row.get("is_public")),
        parse_status=row.get("parse_status") or "pending",
        parse_message=row.get("parse_message") or "",
        chunk_count=chunk_count if chunk_count is not None
        else repo.count_chunks(conn, row["doc_id"]),
        created_at=row.get("created_at") or "",
    )


async def _save_upload(file: UploadFile, *, user_id: int) -> tuple[Path, int]:
    """分块读入并落盘，返回 (保存路径, 文件大小)。同时校验大小上限。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"不支持的文件类型 {suffix or '(无扩展名)'}，当前支持："
            f"{'、'.join(settings.allowed_extensions)}")

    digest = hashlib.sha256()
    size = 0
    chunks: list[bytes] = []
    while True:
        piece = await file.read(_CHUNK)
        if not piece:
            break
        size += len(piece)
        if size > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"文件超过 {settings.max_upload_mb} MB 上限")
        digest.update(piece)
        chunks.append(piece)

    if size == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件为空")

    # 文件名用「用户ID-内容哈希」：天然去重、无路径穿越风险、不暴露原始文件名
    target_dir = settings.upload_dir / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest.hexdigest()[:24]}{suffix}"
    if not target.exists():
        with target.open("wb") as fp:
            for piece in chunks:
                fp.write(piece)
    return target, size


@router.post("", response_model=Envelope, summary="上传课件并解析")
async def upload(file: UploadFile = File(...), course_name: str = Form(""),
                 user: CurrentUser = None, conn: DbDep = None) -> Envelope:  # type: ignore[assignment]
    if user is None or conn is None:  # pragma: no cover - FastAPI 会先做依赖校验
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")

    stored, size = await _save_upload(file, user_id=int(user["user_id"]))

    # 课程名未填写时用原始文件名兜底（落盘名是哈希，不能用来当课程名）
    fallback_course = Path(file.filename or "").stem.strip()
    result = ingest_document(
        conn,
        stored,
        user_id=int(user["user_id"]),
        course_name=(course_name or "").strip() or fallback_course,
        stored_path=str(stored),
        display_name=file.filename or "",
    )

    row = repo.get_document(conn, result["doc_id"])
    if row is None:  # pragma: no cover
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "文档记录写入失败")

    data = UploadOut(
        document=to_document_out(conn, row, chunk_count=result.get("chunks") or 0),
        warnings=result.get("warnings") or [],
        chapters=(result.get("chapters") or [])[:_MAX_CHAPTERS_IN_RESPONSE],
    )
    if result["parse_status"] == "failed":
        # 业务上是「文件不可用」，用 422 让前端走明确的失败分支
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            result.get("message") or "解析失败")
    return Envelope(message="上传并解析完成", data=data.model_dump())


@router.get("", response_model=Envelope, summary="我的材料列表（含公共资料）")
def list_my_documents(user: CurrentUser, conn: DbDep) -> Envelope:
    rows = repo.list_documents(conn, int(user["user_id"]))
    return Envelope(data=[to_document_out(conn, r).model_dump() for r in rows])


@router.get("/courses", response_model=Envelope, summary="我可见的课程清单")
def list_courses(user: CurrentUser, conn: DbDep) -> Envelope:
    return Envelope(data=repo.list_courses(conn, int(user["user_id"])))


@router.get("/{doc_id}", response_model=Envelope, summary="文档详情")
def get_document(doc_id: int, user: CurrentUser, conn: DbDep) -> Envelope:
    if not repo.user_can_access_doc(conn, doc_id, int(user["user_id"])):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在或无权访问")
    row = repo.get_document(conn, doc_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    return Envelope(data=to_document_out(conn, row).model_dump())
