"""会话令牌与 FastAPI 依赖。

鉴权方式：itsdangerous 签名令牌，支持 Cookie（浏览器）与 Bearer（脚本/评测）两种携带方式。
令牌里只有 user_id，权限一律回数据库查，避免令牌内容过期导致的越权。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings
from app.db.conn import business_db

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="cna-session")


def create_token(user_id: int) -> str:
    return _serializer.dumps({"uid": int(user_id)})


def read_token(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    return int(uid) if isinstance(uid, int) else None


# --------------------------------------------------------------------------
# 数据库依赖
# --------------------------------------------------------------------------
def get_db() -> Iterator[sqlite3.Connection]:
    with business_db() as conn:
        yield conn


DbDep = Annotated[sqlite3.Connection, Depends(get_db)]


def get_optional_user(
    conn: DbDep,
    cna_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict | None:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif cna_session:
        token = cna_session
    if not token:
        return None
    uid = read_token(token)
    if uid is None:
        return None
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    return dict(row) if row is not None else None


def get_current_user(user: Annotated[dict | None, Depends(get_optional_user)]) -> dict:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录或登录已过期，请重新登录")
    return user


def require_admin(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]
AdminUser = Annotated[dict, Depends(require_admin)]
OptionalUser = Annotated[dict | None, Depends(get_optional_user)]
