"""FastAPI 应用装配。

启动方式：
    python -m scripts.init_db          # 首次运行先建库
    uvicorn app.main:app --reload      # 开发
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1   # 上线（SQLite 单写者，勿多进程）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import settings
from app.db.conn import BUSINESS_DB, init_databases

logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not BUSINESS_DB.exists():
        logger.warning("未找到数据库 %s，自动初始化（生产环境请先手动执行 scripts/init_db.py）",
                       BUSINESS_DB)
        init_databases()
    logger.info("功能开关：%s", settings.features())
    if settings.secret_key.startswith("dev-only"):
        logger.warning("SECRET_KEY 仍是默认值，上线前必须修改，否则登录态可被伪造")
    yield


app = FastAPI(
    title=settings.app_name,
    description="上传课程课件 → 生成带原文出处的结构化笔记、重点清单与文本思维导图，"
                "并支持材料范围内的问答、历史回看与导出。",
    version="0.1.0",
    lifespan=lifespan,
)

# 前端开发服务器单独跑时需要 CORS；上线同源部署后不影响
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 统一响应格式：所有错误也返回 {code, message, data}
# --------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": str(exc.detail), "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request,
                                        exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    message = f"参数校验失败：{field} {first.get('msg', '')}".strip()
    return JSONResponse(status_code=422,
                        content={"code": 422, "message": message, "data": None})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    detail = f"{type(exc).__name__}: {exc}" if settings.debug else "服务器内部错误，请稍后重试"
    return JSONResponse(status_code=500,
                        content={"code": 500, "message": detail, "data": None})


app.include_router(api_router)


# --------------------------------------------------------------------------
# 前端静态资源（同源部署：Vue 构建产物放 app/static）
# --------------------------------------------------------------------------
def mount_frontend() -> None:
    static_dir = settings.static_dir
    index = static_dir / "index.html"
    if not index.exists():
        logger.info("未找到前端构建产物 %s，跳过静态资源挂载（仅 API 可用）", index)
        return

    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/", include_in_schema=False)
    async def index_page() -> FileResponse:
        return FileResponse(str(index))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        """前端路由（history 模式）回退到 index.html；API 路径不在此列。"""
        candidate = static_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index))


mount_frontend()
