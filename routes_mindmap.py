"""陈瑀涵负责的 U15 导图数据接口。"""
from fastapi import APIRouter, HTTPException

from app.agents.quiz import QuizUnavailable
from app.api.deps import CurrentUser, DbDep
from app.schemas.api_io import Envelope
from app.services.mindmap import build_tree, read_tree

router = APIRouter(prefix="/api/sessions", tags=["mindmap"])


def _run(operation, conn, session_id, user_id):
    try:
        return Envelope(data=operation(conn, session_id, user_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except QuizUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{session_id}/mindmap", response_model=Envelope)
def get_mindmap(session_id: int, user: CurrentUser, conn: DbDep):
    return _run(read_tree, conn, session_id, int(user["user_id"]))


@router.post("/{session_id}/mindmap/build", response_model=Envelope)
def build_mindmap(session_id: int, user: CurrentUser, conn: DbDep):
    return _run(build_tree, conn, session_id, int(user["user_id"]))
