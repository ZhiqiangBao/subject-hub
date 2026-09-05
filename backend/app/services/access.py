from __future__ import annotations

from ..constants import SUBJECTS
from ..models import User


def subject_scope(user: User) -> set[str] | None:
    """None = 全科。"""
    if not user or not getattr(user, "subjects_json", None):
        return None
    raw = str(user.subjects_json).strip()
    if not raw or raw in {"*", "all"}:
        return None
    ids = [s.strip() for s in raw.replace("，", ",").split(",") if s.strip() in SUBJECTS]
    return set(ids) if ids else None


def encode_subjects(ids: list[str]) -> str:
    cleaned = [s for s in ids if s in SUBJECTS]
    if not cleaned or "*" in ids or "all" in ids:
        return "*"
    return ",".join(cleaned)


def sees_subject(user: User, subject: str) -> bool:
    allowed = subject_scope(user)
    return allowed is None or subject in allowed


def scoped_subjects(user: User) -> list[str]:
    allowed = subject_scope(user)
    if allowed is None:
        return list(SUBJECTS)
    return [k for k in SUBJECTS if k in allowed]
