from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import OBJECTIVE_TYPES
from ..models import ItemAnswer
from .bank import Item
from .grade import dump_value, grade_objective, load_value
from .llm import enqueue


def get_or_create_answer(
    db: Session,
    user_id: int,
    context_type: str,
    context_id: int,
    item: Item,
    part_id: str,
) -> ItemAnswer:
    part = next((p for p in item.parts if p.id == part_id), None)
    if not part:
        raise KeyError(part_id)
    row = db.scalar(
        select(ItemAnswer).where(
            ItemAnswer.user_id == user_id,
            ItemAnswer.context_type == context_type,
            ItemAnswer.context_id == context_id,
            ItemAnswer.item_slug == item.slug,
            ItemAnswer.part_id == part_id,
        )
    )
    if row:
        return row
    row = ItemAnswer(
        user_id=user_id,
        context_type=context_type,
        context_id=context_id,
        item_slug=item.slug,
        part_id=part_id,
        max_score=part.points,
        status="draft",
    )
    db.add(row)
    db.flush()
    return row


def save_draft(
    db: Session,
    user_id: int,
    context_type: str,
    context_id: int,
    item: Item,
    parts: dict[str, Any],
) -> None:
    for part in item.parts:
        if part.id not in parts:
            continue
        row = get_or_create_answer(db, user_id, context_type, context_id, item, part.id)
        if row.status not in {"draft", "pending"}:
            continue
        row.value_json = dump_value(parts[part.id])
        row.status = "draft"


def submit_item(
    db: Session,
    user_id: int,
    context_type: str,
    context_id: int,
    item: Item,
    parts: dict[str, Any] | None = None,
    empty_subjective_zero: bool = False,
) -> list[ItemAnswer]:
    now = datetime.utcnow()
    rows: list[ItemAnswer] = []
    if parts:
        save_draft(db, user_id, context_type, context_id, item, parts)
    for part in item.parts:
        row = get_or_create_answer(db, user_id, context_type, context_id, item, part.id)
        if row.status in {"graded", "overridden"} and context_type == "challenge":
            rows.append(row)
            continue
        row.submitted_at = now
        row.max_score = part.points
        photos = []
        try:
            photos = json.loads(row.photos_json or "[]")
        except json.JSONDecodeError:
            photos = []
        if part.type in OBJECTIVE_TYPES:
            row.score = grade_objective(part, load_value(row.value_json))
            row.status = "graded"
            row.graded_at = now
        else:
            text = load_value(row.value_json)
            blank = (text is None or str(text).strip() in {"", "None"}) and not photos
            if empty_subjective_zero and blank:
                row.score = 0
                row.status = "graded"
                row.graded_at = now
            else:
                row.status = "pending"
                enqueue(row.id, item.slug, part.id, photos)
        rows.append(row)
    db.flush()
    return rows


def item_state(
    db: Session,
    user_id: int,
    context_type: str,
    context_id: int,
    item: Item,
    reveal: bool,
) -> dict[str, Any]:
    payload = item.public()
    answers = {}
    submitted = True
    total = 0.0
    max_score = 0.0
    pending = 0
    for part in item.parts:
        row = db.scalar(
            select(ItemAnswer).where(
                ItemAnswer.user_id == user_id,
                ItemAnswer.context_type == context_type,
                ItemAnswer.context_id == context_id,
                ItemAnswer.item_slug == item.slug,
                ItemAnswer.part_id == part.id,
            )
        )
        max_score += part.points
        info: dict[str, Any] = {
            "value": load_value(row.value_json) if row else None,
            "photos": json.loads(row.photos_json) if row and row.photos_json else [],
            "status": row.status if row else "draft",
            "score": None,
            "max_score": part.points,
            "comment": None,
        }
        if row and row.status in {"graded", "overridden"}:
            info["score"] = row.override_score if row.status == "overridden" else row.score
            info["comment"] = row.override_comment or row.llm_comment
            total += float(info["score"] or 0)
        elif row and row.status == "pending":
            pending += 1
        if not row or row.status == "draft":
            submitted = False
        answers[part.id] = info
        if not reveal:
            info.pop("comment", None)
            if info["status"] not in {"graded", "overridden", "pending"}:
                info["score"] = None
    payload["answers"] = answers
    payload["submitted"] = submitted and all(
        answers[p.id]["status"] != "draft" for p in item.parts
    )
    payload["score"] = round(total, 2) if reveal or submitted else None
    payload["max_score"] = max_score
    payload["pending"] = pending
    return payload


def score_context(db: Session, user_id: int, context_type: str, context_id: int, slugs: list[str]) -> dict[str, float | int]:
    rows = db.scalars(
        select(ItemAnswer).where(
            ItemAnswer.user_id == user_id,
            ItemAnswer.context_type == context_type,
            ItemAnswer.context_id == context_id,
            ItemAnswer.item_slug.in_(slugs),
        )
    ).all()
    scored = 0.0
    maximum = 0.0
    pending = 0
    for row in rows:
        maximum += row.max_score or 0
        if row.status == "overridden":
            scored += float(row.override_score or 0)
        elif row.status == "graded":
            scored += float(row.score or 0)
        elif row.status == "pending":
            pending += 1
    return {"score": round(scored, 2), "max_score": round(maximum, 2), "pending": pending}
