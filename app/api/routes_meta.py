"""元信息与健康检查：前端首屏用它决定哪些功能入口显示。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import DbDep, OptionalUser
from app.core.config import settings
from app.schemas.api_io import Envelope

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health", summary="健康检查（部署与评测脚本用）")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@router.get("/meta", response_model=Envelope, summary="系统元信息与功能开关")
def meta(conn: DbDep, user: OptionalUser = None) -> Envelope:
    courses = []
    if user is not None:
        from app.db import repo_business as repo

        courses = repo.list_courses(conn, int(user["user_id"]))
    return Envelope(data={
        "app_name": settings.app_name,
        "features": settings.features(),
        "max_upload_mb": settings.max_upload_mb,
        "allowed_extensions": settings.allowed_extensions,
        "logged_in": user is not None,
        "role": (user or {}).get("role", ""),
        "courses": courses,
    })
