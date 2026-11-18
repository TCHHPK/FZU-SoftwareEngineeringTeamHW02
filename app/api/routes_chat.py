"""FR-05：课程材料问答。

原则：只用检索到的证据回答；检索为空或全部低置信时，直接返回"材料未涉及"，
不把问题交给模型自由发挥。证据不足必须被明确说明（SRS FR-05）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.agents import pipeline
from app.api.deps import CurrentUser, DbDep
from app.db import repo_business as repo
from app.schemas.api_io import AskOut, Envelope
from app.schemas.agent_io import AskRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _resolve_doc_ids(conn, user_id: int, doc_id: int | None, course_name: str) -> list[int]:
    """确定问答范围：指定文档 > 指定课程 > 用户自己全部可用材料。

    范围一定要限定在用户有权访问的材料内，防止串课、串用户。
    """
    if doc_id is not None:
        if not repo.user_can_access_doc(conn, doc_id, user_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在或无权访问")
        return [int(doc_id)]

    rows = repo.list_documents(conn, user_id)
    if course_name:
        rows = [r for r in rows if (r["course_name"] or "") == course_name]
    return [int(r["doc_id"]) for r in rows]


@router.post("/ask", response_model=Envelope, summary="就所选材料提问")
def ask(payload: AskRequest, user: CurrentUser, conn: DbDep) -> Envelope:
    user_id = int(user["user_id"])
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "问题不能为空")

    doc_ids = _resolve_doc_ids(conn, user_id, payload.doc_id, payload.course_name)
    if not doc_ids:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "还没有可用的材料，请先上传课件并完成解析")

    answer = pipeline.answer_question(conn, question=question, doc_ids=doc_ids,
                                      course_name=payload.course_name)

    repo.save_chat(conn, user_id=user_id, role="user", content=question,
                   course_name=payload.course_name, doc_id=payload.doc_id)
    repo.save_chat(conn, user_id=user_id, role="assistant", content=answer.answer,
                   course_name=payload.course_name, doc_id=payload.doc_id,
                   evidence=answer.evidence, insufficient=answer.insufficient)

    data = AskOut(course_name=payload.course_name, **answer.model_dump())
    return Envelope(message="回答完成（依据材料内容）" if not answer.insufficient else "材料未涉及",
                    data=data.model_dump())


@router.get("/history", response_model=Envelope, summary="问答历史")
def history(user: CurrentUser, conn: DbDep,
            course_name: str | None = Query(None),
            limit: int = Query(30, ge=1, le=100)) -> Envelope:
    rows = repo.list_chats(conn, int(user["user_id"]), course_name=course_name, limit=limit)
    return Envelope(data=rows)
