from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import Paper, PaperAttempt
from .answers import score_context


def paper_ends_at(paper: Paper) -> datetime | None:
    minutes = int(getattr(paper, "duration_minutes", 0) or 0)
    if minutes <= 0 or not paper.created_at:
        return None
    return paper.created_at + timedelta(minutes=minutes)


def paper_remaining_sec(paper: Paper, now: datetime | None = None) -> int | None:
    end = paper_ends_at(paper)
    if end is None:
        return None
    now = now or datetime.utcnow()
    return max(0, int((end - now).total_seconds()))


def paper_expired(paper: Paper) -> bool:
    left = paper_remaining_sec(paper)
    return left is not None and left <= 0


def timing_fields(paper: Paper) -> dict[str, Any]:
    remaining = paper_remaining_sec(paper)
    return {
        "duration_minutes": int(getattr(paper, "duration_minutes", 0) or 0),
        "remaining_sec": remaining,
        "timed": remaining is not None,
        "expired": remaining is not None and remaining <= 0,
    }


def paper_ranking(db: Session, paper: Paper) -> list[dict[str, Any]]:
    slugs = json.loads(paper.slugs_json)
    rows = []
    for attempt in paper.attempts:
        ctx = score_context(db, attempt.user_id, "paper", attempt.id, slugs)
        student = attempt.user
        rows.append(
            {
                "attempt_id": attempt.id,
                "user_id": attempt.user_id,
                "name": (student.display_name or student.username) if student else "",
                "status": "已交卷" if attempt.status == "submitted" else "未交卷",
                "submitted": attempt.status == "submitted",
                "pending": int(ctx["pending"]),
                "score": ctx["score"],
                "max_score": ctx["max_score"],
                "complete": attempt.status == "submitted" and int(ctx["pending"]) == 0,
            }
        )
    complete = sorted(
        [r for r in rows if r["complete"]],
        key=lambda r: (-float(r["score"]), r["name"]),
    )
    rank_of = {r["user_id"]: i + 1 for i, r in enumerate(complete)}
    total = len(complete)
    for row in rows:
        row["rank"] = rank_of.get(row["user_id"])
        row["rank_total"] = total
    rows.sort(key=lambda r: (0 if r["complete"] else 1, -(float(r["score"]) if r["submitted"] else -1), r["name"]))
    return rows
