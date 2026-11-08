from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import OBJECTIVE_TYPES, SUBJECTS, TYPES
from ..models import ChallengeRun, ItemAnswer, PaperAttempt, User
from .bank import BankError, bank
from .grade import load_value
from .grade_jobs import GradeJob
from .snapshots import context_item
from .groups import teacher_label


def _status_label(status: str) -> str:
    return {
        "draft": "未交",
        "pending": "待评分",
        "graded": "已评分",
        "overridden": "已改判",
    }.get(status, status)


def _show_value(value: Any) -> str:
    if value is None or value == "":
        return "（没写）"
    if isinstance(value, list):
        return "、".join(str(x) for x in value) or "（没写）"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _part_review(db: Session, user_id: int, context_type: str, context_id: int, slug: str, part) -> dict[str, Any]:
    row = db.scalar(
        select(ItemAnswer).where(
            ItemAnswer.user_id == user_id,
            ItemAnswer.context_type == context_type,
            ItemAnswer.context_id == context_id,
            ItemAnswer.item_slug == slug,
            ItemAnswer.part_id == part.id,
        )
    )
    status = row.status if row else "draft"
    photos = []
    if row and row.photos_json:
        try:
            photos = json.loads(row.photos_json)
        except json.JSONDecodeError:
            photos = []
    from .answers import effective_comment, effective_score

    return {
        "answer_id": row.id if row else None,
        "part_id": part.id,
        "type": part.type,
        "type_name": TYPES.get(part.type, part.type),
        "stem": part.stem,
        "subjective": part.type not in OBJECTIVE_TYPES,
        "job_state": db.scalar(select(GradeJob.state).where(GradeJob.answer_id == row.id))
        if row and part.type not in OBJECTIVE_TYPES else None,
        "value": load_value(row.value_json) if row else None,
        "value_text": _show_value(load_value(row.value_json) if row else None),
        "photos": photos,
        "status": status,
        "status_label": _status_label(status),
        "score": effective_score(row),
        "llm_score": row.score if row else None,
        "admin_score": row.override_score if row else None,
        "raw_score": row.score if row else None,
        "max_score": part.points,
        "comment": effective_comment(row),
        "llm_comment": row.llm_comment if row else None,
        "admin_comment": row.override_comment if row else None,
        "admin_touched": bool(row and row.override_score is not None),
        "reference": part.reference,
        "rubric": part.rubric,
        "choices": [{"id": c["id"], "text": c["text"]} for c in (part.choices or [])],
    }


def _item_review(db: Session, user_id: int, context_type: str, context_id: int, slug: str, index: int) -> dict[str, Any]:
    item = context_item(db, context_type, context_id, slug)
    if not item:
        from .answers import effective_score

        rows = db.scalars(select(ItemAnswer).where(
            ItemAnswer.user_id == user_id, ItemAnswer.context_type == context_type,
            ItemAnswer.context_id == context_id, ItemAnswer.item_slug == slug,
        )).all()
        return {
            "index": index,
            "slug": slug,
            "title": slug,
            "left_md": "",
            "tags": [],
            "missing": True,
            "score": round(sum(effective_score(row) or 0 for row in rows if row.status in {"graded", "overridden"}), 2),
            "max_score": round(sum(row.max_score or 0 for row in rows), 2),
            "pending": sum(row.status in {"pending", "submitted"} for row in rows),
            "parts": [],
        }
    parts = [_part_review(db, user_id, context_type, context_id, slug, part) for part in item.parts]
    scored = sum(float(p["score"] or 0) for p in parts if p["score"] is not None)
    maximum = sum(float(p["max_score"] or 0) for p in parts)
    pending = sum(1 for p in parts if p["status"] == "pending")
    return {
        "index": index,
        "slug": slug,
        "title": item.title,
        "left_md": item.left_md,
        "tags": list(item.tags),
        "missing": False,
        "score": round(scored, 2),
        "max_score": round(maximum, 2),
        "pending": pending,
        "parts": parts,
    }


def review_challenge(db: Session, run_id: int) -> dict[str, Any]:
    run = db.get(ChallengeRun, run_id)
    if not run:
        return {}
    student = db.get(User, run.user_id)
    slugs = json.loads(run.slugs_json)
    items = [_item_review(db, run.user_id, "challenge", run.id, slug, i) for i, slug in enumerate(slugs)]
    return {
        "kind": "challenge",
        "id": run.id,
        "title": f"闯关 · {SUBJECTS.get(run.subject, run.subject)}",
        "status": "进行中" if run.status == "active" else "已完成",
        "anonymous": False,
        "can_grade": True,
        "student_id": run.user_id,
        "student": teacher_label(student),
        "items": items,
        "score": round(sum(i["score"] for i in items), 2),
        "max_score": round(sum(i["max_score"] for i in items), 2),
        "pending": sum(i["pending"] for i in items),
    }


def review_paper(db: Session, attempt_id: int, *, named: bool = False) -> dict[str, Any]:
    attempt = db.get(PaperAttempt, attempt_id)
    if not attempt:
        return {}
    paper = attempt.paper
    slugs = json.loads(paper.slugs_json)
    items = [_item_review(db, attempt.user_id, "paper", attempt.id, slug, i) for i, slug in enumerate(slugs)]
    student = db.get(User, attempt.user_id) if named else None
    return {
        "kind": "paper",
        "id": attempt.id,
        "paper_id": paper.id if paper else None,
        "title": paper.title if paper else "试卷",
        "status": "已交卷" if attempt.status == "submitted" else "未交卷",
        "anonymous": not named,
        "can_grade": bool(not named and attempt.status in {"submitted", "absent"}
                          and paper.grading_started_at and not paper.scores_released_at),
        "student_id": attempt.user_id if named else None,
        "student": teacher_label(student),
        "items": items,
        "score": round(sum(i["score"] for i in items), 2),
        "max_score": round(sum(i["max_score"] for i in items), 2),
        "pending": sum(i["pending"] for i in items),
    }
