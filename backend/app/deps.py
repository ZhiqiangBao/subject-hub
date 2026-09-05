from __future__ import annotations

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import ADMIN_PORT, PORT
from .db import get_db
from .models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def user_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(User)) or 0)


def listen_port(request: Request) -> int:
    server = request.scope.get("server")
    if server and len(server) > 1 and server[1]:
        return int(server[1])
    return int(request.url.port or PORT)


def is_admin_site(request: Request) -> bool:
    return listen_port(request) == ADMIN_PORT


def is_admin_role(user: User) -> bool:
    return user.role in {"admin", "parent"}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    user = db.get(User, int(user_id))
    if not user:
        request.session.clear()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not is_admin_role(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "这一页给管理员用")
    return user


def get_parent_user(user: User = Depends(get_current_user)) -> User:
    if not is_admin_role(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "这一页给管理员用")
    return user
