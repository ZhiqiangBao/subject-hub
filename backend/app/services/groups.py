from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constants import grade_label
from ..models import Paper, StudentGroup, StudentGroupMember, User


def group_label(group: StudentGroup | None) -> str:
    if not group:
        return "未分组"
    if group.kind == "class":
        return f"{grade_label(group.grade)}{group.name}"
    if group.parent_id and group.parent:
        return f"{group_label(group.parent)} / {group.name}"
    return group.name


def member_count(db: Session, group_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(StudentGroupMember.id)).where(StudentGroupMember.group_id == group_id)
        )
        or 0
    )


def group_row(db: Session, group: StudentGroup) -> dict:
    parent = group.parent
    return {
        "id": group.id,
        "name": group.name,
        "kind": group.kind,
        "is_class": group.kind == "class",
        "grade": group.grade,
        "grade_name": grade_label(group.grade) if group.grade else "",
        "parent_id": group.parent_id,
        "parent_label": group_label(parent) if parent else "",
        "label": group_label(group),
        "count": member_count(db, group.id),
    }


def list_groups(db: Session) -> list[dict]:
    rows = db.scalars(
        select(StudentGroup).order_by(StudentGroup.kind, StudentGroup.grade, StudentGroup.parent_id, StudentGroup.name, StudentGroup.id)
    ).all()
    return [group_row(db, g) for g in rows]


def ungrouped_count(db: Session) -> int:
    members = select(StudentGroupMember.user_id).distinct()
    return int(
        db.scalar(select(func.count(User.id)).where(User.role == "student", User.id.not_in(members))) or 0
    )


def group_students(db: Session, group_id: int | None) -> list[User]:
    if group_id is None:
        members = select(StudentGroupMember.user_id).distinct()
        return list(
            db.scalars(select(User).where(User.role == "student", User.id.not_in(members)).order_by(User.id)).all()
        )
    ids = select(StudentGroupMember.user_id).where(StudentGroupMember.group_id == group_id)
    return list(db.scalars(select(User).where(User.role == "student", User.id.in_(ids)).order_by(User.id)).all())


def require_group(db: Session, group_id: int | None) -> StudentGroup:
    if not group_id:
        raise HTTPException(400, "请选一个分组")
    group = db.get(StudentGroup, group_id)
    if not group:
        raise HTTPException(400, "找不到这个分组")
    return group


def user_group_ids(user: User) -> set[int]:
    return {m.group_id for m in (user.memberships or [])}


def teacher_label(user: User | None) -> str:
    if not user:
        return ""
    return (user.display_name or "").strip() or user.username


def student_public(user: User) -> dict:
    groups = [m.group for m in (user.memberships or []) if m.group]
    groups.sort(key=lambda g: (0 if g.kind == "class" else 1, g.parent_id or 0, g.id))
    class_group = next((g for g in groups if g.kind == "class"), None)
    return {
        "id": user.id,
        "username": user.username,
        "display_name": teacher_label(user),
        "grade": user.grade,
        "grade_name": grade_label(user.grade),
        "group_ids": [g.id for g in groups],
        "groups": [{"id": g.id, "name": g.name, "kind": g.kind, "label": group_label(g), "is_class": g.kind == "class"} for g in groups],
        "class_label": group_label(class_group) if class_group else "未分班",
        "group_label": "、".join(group_label(g) for g in groups) or "未分组",
        "self_registered": user.created_by is None,
    }


def _has_member(db: Session, user_id: int, group_id: int) -> bool:
    return (
        db.scalar(
            select(StudentGroupMember.id).where(
                StudentGroupMember.user_id == user_id, StudentGroupMember.group_id == group_id
            )
        )
        is not None
    )


def add_membership(db: Session, student: User, group: StudentGroup) -> None:
    chain: list[StudentGroup] = [group]
    parent = group.parent
    while parent is not None:
        chain.append(parent)
        parent = parent.parent
    for item in chain:
        if not _has_member(db, student.id, item.id):
            db.add(StudentGroupMember(user_id=student.id, group_id=item.id))
    class_group = next((g for g in chain if g.kind == "class" and g.grade), None)
    if class_group:
        student.grade = class_group.grade


def remove_membership(db: Session, student: User, group: StudentGroup) -> None:
    drop = {group.id}
    for child in group.children or []:
        drop.add(child.id)
    for row in list(student.memberships or []):
        if row.group_id in drop:
            db.delete(row)


def set_memberships(db: Session, student: User, group_ids: list[int] | None, grade: int | None = None) -> None:
    if group_ids is None:
        if grade:
            student.grade = grade
        return
    wanted: list[StudentGroup] = []
    seen: set[int] = set()
    for gid in group_ids:
        group = require_group(db, gid)
        if group.id in seen:
            continue
        seen.add(group.id)
        wanted.append(group)
    keep: set[int] = set()
    for group in wanted:
        add_membership(db, student, group)
        keep.add(group.id)
        parent = group.parent
        while parent is not None:
            keep.add(parent.id)
            parent = parent.parent
    db.flush()
    rows = db.scalars(select(StudentGroupMember).where(StudentGroupMember.user_id == student.id)).all()
    for row in rows:
        if row.group_id not in keep:
            db.delete(row)
    if grade:
        student.grade = grade
    elif not student.grade:
        class_group = next((g for g in wanted if g.kind == "class" and g.grade), None)
        if class_group:
            student.grade = class_group.grade


def roster_for_paper(db: Session, paper: Paper) -> list[User]:
    gids = [a.group_id for a in (paper.audiences or [])]
    if not gids:
        return []
    ids = select(StudentGroupMember.user_id).where(StudentGroupMember.group_id.in_(gids)).distinct()
    return list(db.scalars(select(User).where(User.role == "student", User.id.in_(ids)).order_by(User.id)).all())


def audience_payload(paper: Paper) -> list[dict]:
    from .timing import utc_iso

    out = []
    for row in paper.audiences or []:
        group = row.group
        out.append(
            {
                "group_id": row.group_id,
                "name": group.name if group else "",
                "label": group_label(group),
                "kind": group.kind if group else "group",
                "grade": group.grade if group else None,
                "opens_at": utc_iso(row.opens_at),
                "closes_at": utc_iso(row.closes_at),
            }
        )
    out.sort(key=lambda r: (r.get("grade") or 0, r["group_id"]))
    return out
