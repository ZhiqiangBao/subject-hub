from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import SUBJECTS
from ..db import get_db
from ..deps import get_current_user, hash_password, is_admin_site, verify_password
from ..models import User
from ..schemas import LoginIn, RegisterIn, UserOut
from ..services.access import encode_subjects

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def auth_status(request: Request) -> dict[str, bool]:
    return {"admin_site": is_admin_site(request)}


@router.post("/register", response_model=UserOut)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> User:
    name = body.username.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请写一个名字")
    exists = db.scalar(select(User).where(User.username == name))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "这个名字已经有人用了")
    admin = is_admin_site(request)
    subjects = "*"
    if admin:
        wanted = [s for s in body.subjects if s in SUBJECTS or s in {"*", "all"}]
        subjects = encode_subjects(wanted)
    user = User(
        username=name,
        password_hash=hash_password(body.password),
        role="admin" if admin else "student",
        display_name=name,
        subjects_json=subjects if admin else "*",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session["user_id"] = user.id
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "名字或密码不对")
    request.session["user_id"] = user.id
    return user


@router.post("/logout")
def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
