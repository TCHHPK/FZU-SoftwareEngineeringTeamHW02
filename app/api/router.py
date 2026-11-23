"""路由汇总。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api import (
    routes_admin,
    routes_auth,
    routes_chat,
    routes_meta,
    routes_mindmap,
    routes_self_test,
    routes_sessions,
    routes_uploads,
    routes_wrong,
)

logger = logging.getLogger(__name__)

api_router = APIRouter()
api_router.include_router(routes_meta.router)
api_router.include_router(routes_auth.router)
api_router.include_router(routes_uploads.router)
api_router.include_router(routes_sessions.router)
api_router.include_router(routes_chat.router)
api_router.include_router(routes_admin.router)
api_router.include_router(routes_wrong.router)
api_router.include_router(routes_mindmap.router)
api_router.include_router(routes_self_test.router)

# v1.3.0（Beta）：复习包 / 冲刺计划 / 出处抽屉的端点由沈文驰在
# app/api/routes_review.py 交付，路由登记归徐张睿（本文件唯一所有者）。
# 这里用「可选导入」而不是硬 import：他的模块 11.28 才到位，
# 在那之前若直接 import 会让整个应用起不来（上一轮导图路由就是这么炸的）。
# 模块一到，重启即自动挂上，不需要再改本文件。
try:
    from app.api import routes_review
except ImportError:  # pragma: no cover - 仅在队友模块尚未交付时触发
    logger.info("routes_review 尚未交付，复习包相关端点暂不挂载")
else:
    api_router.include_router(routes_review.router)
