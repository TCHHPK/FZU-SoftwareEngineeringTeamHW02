"""路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    routes_admin,
    routes_auth,
    routes_chat,
    routes_meta,
    routes_sessions,
    routes_uploads,
    routes_wrong,
)

api_router = APIRouter()
api_router.include_router(routes_meta.router)
api_router.include_router(routes_auth.router)
api_router.include_router(routes_uploads.router)
api_router.include_router(routes_sessions.router)
api_router.include_router(routes_chat.router)
api_router.include_router(routes_admin.router)
api_router.include_router(routes_wrong.router)
