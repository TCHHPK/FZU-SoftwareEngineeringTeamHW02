"""智能自测接口（U14）：组卷、取卷、交卷、历史。

四个端点对应智能自测的完整闭环：
    POST /api/self-tests            组卷（异步出题，返回 test_id）
    GET  /api/self-tests            我的自测列表
    GET  /api/self-tests/{id}       取卷（未判分不下发答案）
    POST /api/self-tests/{id}/submit 交卷（判分 + 错题回填，幂等）

约定与项目其他接口一致：统一 Envelope、Cookie/Bearer 双鉴权、越权返回 404。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, DbDep
from app.schemas.api_io import Envelope, SelfTestCreate, SelfTestSubmit
from app.services import quiz

router = APIRouter(prefix="/api/self-tests", tags=["self-test"])


@router.post("", response_model=Envelope, status_code=status.HTTP_202_ACCEPTED,
             summary="组卷（异步出题，返回 test_id 后轮询取卷）")
def create_self_test(payload: SelfTestCreate, user: CurrentUser, conn: DbDep,
                     background: BackgroundTasks) -> JSONResponse:
    try:
        test_id = quiz.create_test(
            conn,
            user_id=int(user["user_id"]),
            session_id=payload.session_id,
            question_count=payload.question_count,
            scope_text=payload.scope_text,
        )
    except quiz.QuizError as exc:
        raise HTTPException(exc.status, exc.message) from exc

    # 出题可能调用模型，放到后台执行；接口先返回，前端轮询 GET /self-tests/{id}
    background.add_task(quiz.build_items_job, test_id)

    body = Envelope(code=0, message="已创建，正在出题", data={
        "test_id": test_id,
        "status": "draft",
        "question_count": payload.question_count,
    })
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body.model_dump())


@router.get("", response_model=Envelope, summary="我的自测列表")
def list_self_tests(user: CurrentUser, conn: DbDep,
                    limit: int = Query(50, ge=1, le=200)) -> Envelope:
    rows = quiz.list_tests(conn, user_id=int(user["user_id"]), limit=limit)
    return Envelope(data=rows)


@router.get("/{test_id}", response_model=Envelope, summary="取卷（answer 仅在判分后返回）")
def get_self_test(test_id: int, user: CurrentUser, conn: DbDep) -> Envelope:
    try:
        data = quiz.get_test(conn, test_id=test_id, user_id=int(user["user_id"]))
    except quiz.QuizError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return Envelope(data=data)


@router.post("/{test_id}/submit", response_model=Envelope,
             summary="交卷：判分 + 错题回填（同一事务，重复提交幂等）")
def submit_self_test(test_id: int, payload: SelfTestSubmit, user: CurrentUser,
                     conn: DbDep) -> Envelope:
    try:
        data = quiz.submit_test(
            conn,
            test_id=test_id,
            user_id=int(user["user_id"]),
            answers=[a.model_dump() for a in payload.answers],
        )
    except quiz.QuizError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return Envelope(message="已判分", data=data)
