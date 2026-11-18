"""错题本（U13）接口。

三个端点（契约表 5）：
    GET  /api/wrong-questions              错题列表 + 按知识点的薄弱度聚合
    GET  /api/wrong-questions/{id}         错题详情（含解析与出处）
    POST /api/wrong-questions/{id}/retry   重做一题：判分 + 更新连对/掌握状态

越权一律 404（不区分「不存在」与「无权」，避免枚举他人错题）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbDep
from app.schemas.api_io import Envelope, RetryRequest
from app.services import wrong_book

router = APIRouter(prefix="/api/wrong-questions", tags=["wrong-questions"])


@router.get("", response_model=Envelope, summary="错题列表 + 按知识点的薄弱度聚合")
def list_wrong(
    user: CurrentUser,
    conn: DbDep,
    knowledge_name: str | None = Query(None, max_length=64, description="按知识点筛选"),
    mastered: int | None = Query(None, ge=0, le=1, description="1 仅看已掌握，0 仅看未掌握"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Envelope:
    data = wrong_book.list_wrong_questions(
        conn, int(user["user_id"]),
        knowledge_name=knowledge_name, mastered=mastered,
        limit=limit, offset=offset,
    )
    return Envelope(data=data)


@router.get("/{wrong_id}", response_model=Envelope, summary="错题详情（含解析与出处）")
def get_wrong(wrong_id: int, user: CurrentUser, conn: DbDep) -> Envelope:
    data = wrong_book.get_wrong_question(conn, int(user["user_id"]), wrong_id)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错题不存在或无权访问")
    return Envelope(data=data)


@router.post("/{wrong_id}/retry", response_model=Envelope,
             summary="重做一题：判定对错、更新连对次数与掌握状态")
def retry_wrong(wrong_id: int, payload: RetryRequest,
                user: CurrentUser, conn: DbDep) -> Envelope:
    data = wrong_book.retry_wrong_question(
        conn, int(user["user_id"]), wrong_id, payload.answer)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "错题不存在或无权访问")
    return Envelope(message="判分完成", data=data)
