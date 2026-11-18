"""FR-01：注册、登录、登出、当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbDep, create_token
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db import repo_business as repo
from app.schemas.api_io import Envelope, LoginOut, LoginRequest, RegisterRequest, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USERNAME_MIN = 3
_USERNAME_MAX = 32
_PASSWORD_MIN = 6


def _user_out(row: dict) -> UserOut:
    return UserOut(user_id=row["user_id"], username=row["username"],
                   nickname=row.get("nickname") or "", role=row.get("role") or "student",
                   created_at=row.get("created_at") or "")


def _validate_username(username: str) -> str:
    name = (username or "").strip()
    if not (_USERNAME_MIN <= len(name) <= _USERNAME_MAX):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"用户名长度需为 {_USERNAME_MIN}~{_USERNAME_MAX} 个字符")
    return name


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # 上线启用 HTTPS 后改为 True
        path="/",
    )


@router.post("/register", response_model=Envelope, summary="注册")
def register(payload: RegisterRequest, response: Response, conn: DbDep) -> Envelope:
    username = _validate_username(payload.username)
    if len(payload.password) < _PASSWORD_MIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"密码至少 {_PASSWORD_MIN} 位")
    if repo.get_user_by_username(conn, username):
        raise HTTPException(status.HTTP_409_CONFLICT, "该用户名已被注册")

    user_id = repo.create_user(conn, username, hash_password(payload.password),
                               payload.nickname.strip())
    row = repo.get_user(conn, user_id)
    token = create_token(user_id)
    _set_session_cookie(response, token)
    return Envelope(message="注册成功", data=LoginOut(token=token, user=_user_out(row)).model_dump())


@router.post("/login", response_model=Envelope, summary="登录")
def login(payload: LoginRequest, response: Response, conn: DbDep) -> Envelope:
    row = repo.get_user_by_username(conn, (payload.username or "").strip())
    # 统一提示，不透露「用户名是否存在」
    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")

    token = create_token(int(row["user_id"]))
    _set_session_cookie(response, token)
    return Envelope(message="登录成功", data=LoginOut(token=token, user=_user_out(row)).model_dump())


@router.post("/logout", response_model=Envelope, summary="登出")
def logout(response: Response) -> Envelope:
    response.delete_cookie(settings.cookie_name, path="/")
    return Envelope(message="已退出登录")


@router.get("/me", response_model=Envelope, summary="当前用户")
def me(user: CurrentUser) -> Envelope:
    return Envelope(data=_user_out(user).model_dump())
