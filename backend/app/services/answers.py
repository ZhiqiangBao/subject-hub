from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import OBJECTIVE_TYPES
from ..models import ItemAnswer, Paper, PaperAttempt
from .bank import Item, bank
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


def admin_touched(row: ItemAnswer | None) -> bool:
    return bool(row and row.override_score is not None)


def effective_score(row: ItemAnswer | None) -> float | None:
    if not row:
        return None
    if row.override_score is not None:
        return float(row.override_score)
    if row.score is not None:
        return float(row.score)
    return None


def effective_comment(row: ItemAnswer | None) -> str | None:
    if not row:
        return None
    if row.override_score is not None:
        return row.override_comment
    return row.llm_comment


def apply_llm_score(row: ItemAnswer, score: float, comment: str | None = None, llm_json: str | None = None) -> None:
    row.score = float(score)
    if comment is not None:
        row.llm_comment = comment
    if llm_json is not None:
        row.llm_json = llm_json
    row.graded_at = datetime.utcnow()
    if row.override_score is None:
        row.status = "graded"
    else:
        row.status = "overridden"


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
        if row.status not in {"draft", "pending", "submitted"}:
            continue
        row.value_json = dump_value(parts[part.id])
        if row.status != "submitted":
            row.status = "draft"


def _photos(row: ItemAnswer) -> list[str]:
    try:
        return json.loads(row.photos_json or "[]")
    except json.JSONDecodeError:
        return []


def collect_item(
    db: Session,
    user_id: int,
    context_type: str,
    context_id: int,
    item: Item,
    parts: dict[str, Any] | None = None,
) -> list[ItemAnswer]:
    now = datetime.utcnow()
    rows: list[ItemAnswer] = []
    if parts:
        save_draft(db, user_id, context_type, context_id, item, parts)
    for part in item.parts:
        row = get_or_create_answer(db, user_id, context_type, context_id, item, part.id)
        if row.status in {"graded", "overridden", "pending"} and context_type == "challenge":
            rows.append(row)
            continue
        row.submitted_at = now
        row.max_score = part.points
        if row.status not in {"graded", "overridden", "pending"}:
            row.status = "submitted"
        rows.append(row)
    db.flush()
    return rows


def machine_grade_row(row: ItemAnswer, item: Item, empty_subjective_zero: bool = False) -> None:
    part = next((p for p in item.parts if p.id == row.part_id), None)
    if not part:
        return
    now = datetime.utcnow()
    photos = _photos(row)
    if part.type in OBJECTIVE_TYPES:
        apply_llm_score(row, grade_objective(part, load_value(row.value_json)))
        return
    text = load_value(row.value_json)
    blank = (text is None or str(text).strip() in {"", "None"}) and not photos
    if empty_subjective_zero and blank:
        apply_llm_score(row, 0.0, comment="")
        return
    if row.override_score is None:
        row.status = "pending"
    enqueue(row.id, item.slug, part.id, photos)
    row.graded_at = now


def machine_grade_item(
    db: Session,
    user_id: int,
    context_type: str,
    context_id: int,
    item: Item,
    empty_subjective_zero: bool = False,
) -> list[ItemAnswer]:
    rows: list[ItemAnswer] = []
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
        if not row or row.status == "draft":
            continue
        machine_grade_row(row, item, empty_subjective_zero)
        rows.append(row)
    db.flush()
    return rows


def submit_item(
    db: Session,
    user_id: int,
    context_type: str,
    context_id: int,
    item: Item,
    parts: dict[str, Any] | None = None,
    empty_subjective_zero: bool = False,
    grade: bool = True,
) -> list[ItemAnswer]:
    rows = collect_item(db, user_id, context_type, context_id, item, parts)
    if not grade:
        return rows
    for row in rows:
        try:
            machine_grade_row(row, item, empty_subjective_zero)
        except Exception:
            continue
    db.flush()
    return rows


def grade_paper_attempts(db: Session, paper: Paper) -> int:
    slugs = json.loads(paper.slugs_json)
    empty_zero = bool(paper.duration_minutes) or paper.kind == "exam"
    n = 0
    for attempt in paper.attempts:
        if attempt.status not in {"submitted"}:
            continue
        for slug in slugs:
            if slug not in bank.items:
                continue
            item = bank.get(slug)
            machine_grade_item(db, attempt.user_id, "paper", attempt.id, item, empty_zero)
            n += 1
    return n


def item_is_saved(
    db: Session,
    user_id: int,
    context_type: str,
    context_id: int,
    item: Item,
) -> bool:
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
        if not row:
            return False
    return True


def paper_save_progress(db: Session, user_id: int, attempt_id: int, slugs: list[str]) -> dict[str, Any]:
    saved: list[str] = []
    missing: list[str] = []
    for slug in slugs:
        item = bank.items.get(slug)
        if not item:
            missing.append(slug)
            continue
        if item_is_saved(db, user_id, "paper", attempt_id, item):
            saved.append(slug)
        else:
            missing.append(slug)
    return {
        "saved_slugs": saved,
        "missing_slugs": missing,
        "all_saved": not missing,
        "saved_count": len(saved),
        "item_count": len(slugs),
    }


def scores_visible_for_paper(paper: Paper | None) -> bool:
    return bool(paper and paper.scores_released_at)


SCORED_STATUSES = {"graded", "overridden"}


def paper_part_count(paper: Paper) -> int:
    n = 0
    for slug in json.loads(paper.slugs_json or "[]"):
        item = bank.items.get(slug)
        if item:
            n += len(item.parts)
    return n


def settle_closed_groups(db: Session, paper: Paper) -> None:
    from .groups import roster_for_paper
    from .timing import audience_for_user, paper_window

    slugs = json.loads(paper.slugs_json or "[]")
    now = datetime.utcnow()
    roster = roster_for_paper(db, paper)
    if not roster:
        if paper_window(paper) != "closed":
            return
        for attempt in paper.attempts:
            if attempt.status in {"submitted", "absent"}:
                continue
            for slug in slugs:
                if slug in bank.items:
                    submit_item(db, attempt.user_id, "paper", attempt.id, bank.get(slug), None, grade=False)
            attempt.status = "submitted"
            attempt.submitted_at = now
        return
    by_user = {a.user_id: a for a in paper.attempts}
    for student in roster:
        aud = audience_for_user(paper, student)
        if paper_window(paper, audience=aud) != "closed":
            continue
        attempt = by_user.get(student.id)
        if not attempt:
            attempt = PaperAttempt(paper_id=paper.id, user_id=student.id, status="draft")
            db.add(attempt)
            db.flush()
            by_user[student.id] = attempt
            for slug in slugs:
                if slug in bank.items:
                    submit_item(
                        db,
                        student.id,
                        "paper",
                        attempt.id,
                        bank.get(slug),
                        None,
                        grade=True,
                        empty_subjective_zero=True,
                    )
            attempt.status = "absent"
            attempt.submitted_at = now
            continue
        if attempt.status in {"submitted", "absent"}:
            continue
        for slug in slugs:
            if slug in bank.items:
                submit_item(db, student.id, "paper", attempt.id, bank.get(slug), None, grade=False)
        attempt.status = "submitted"
        attempt.submitted_at = now


def paper_ungraded_count(db: Session, paper: Paper) -> int:
    """已到截止的对象里，还没机评完（含模型排队、缺考未入账）的问数。"""
    from .groups import roster_for_paper
    from .timing import audience_for_user, paper_window

    slugs = json.loads(paper.slugs_json or "[]")
    roster = roster_for_paper(db, paper)
    students = roster or [a.user for a in paper.attempts if a.user]
    n = 0
    parts_n = paper_part_count(paper)
    by_user = {a.user_id: a for a in paper.attempts}
    for student in students:
        if not student:
            continue
        aud = audience_for_user(paper, student)
        if roster and paper_window(paper, audience=aud) != "closed":
            continue
        if not roster and paper_window(paper) != "closed":
            attempt = by_user.get(student.id)
            if attempt and attempt.status in {"submitted", "absent"}:
                pass
            else:
                continue
        attempt = by_user.get(student.id)
        if not attempt or attempt.status == "draft":
            n += parts_n
            continue
        rows = db.scalars(
            select(ItemAnswer).where(
                ItemAnswer.user_id == student.id,
                ItemAnswer.context_type == "paper",
                ItemAnswer.context_id == attempt.id,
            )
        ).all()
        by_part = {(r.item_slug, r.part_id): r for r in rows}
        for slug in slugs:
            item = bank.items.get(slug)
            if not item:
                continue
            for part in item.parts:
                row = by_part.get((slug, part.id))
                if not row or row.status not in SCORED_STATUSES:
                    n += 1
    return n


def paper_can_release_scores(db: Session, paper: Paper) -> bool:
    from .timing import paper_all_windows_closed

    if not getattr(paper, "grading_started_at", None) or getattr(paper, "scores_released_at", None):
        return False
    if not paper_all_windows_closed(paper):
        return False
    return paper_ungraded_count(db, paper) == 0


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
            "llm_score": row.score if row else None,
            "admin_score": row.override_score if row else None,
            "max_score": part.points,
            "comment": None,
        }
        pts = effective_score(row)
        if pts is not None and row and row.status in {"graded", "overridden"}:
            info["score"] = pts
            info["comment"] = effective_comment(row)
            total += float(pts)
        elif row and row.status in {"pending", "submitted"}:
            pending += 1
        if not row or row.status == "draft":
            submitted = False
        answers[part.id] = info
        if not reveal:
            info.pop("comment", None)
            info["score"] = None
            info["llm_score"] = None
            info["admin_score"] = None
    payload["answers"] = answers
    payload["submitted"] = submitted and all(
        answers[p.id]["status"] != "draft" for p in item.parts
    )
    payload["score"] = round(total, 2) if reveal else None
    payload["max_score"] = max_score
    payload["pending"] = pending if reveal else 0
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
    has_score = False
    for row in rows:
        maximum += row.max_score or 0
        pts = effective_score(row)
        if pts is not None and row.status in {"graded", "overridden"}:
            scored += pts
            has_score = True
        elif row.status in {"pending", "submitted"}:
            pending += 1
    return {
        "score": round(scored, 2) if has_score else 0,
        "max_score": round(maximum, 2),
        "pending": pending,
    }
