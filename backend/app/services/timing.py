from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import Paper, User
from .answers import score_context
from .groups import teacher_label


def utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return utc_naive(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def paper_released(paper: Paper) -> bool:
    return bool(getattr(paper, "released_at", None))


def audience_for_user(paper: Paper, user: User | None):
    if user is None:
        return None
    from .groups import user_group_ids

    ids = user_group_ids(user)
    auds = list(getattr(paper, "audiences", None) or [])
    if not auds or not ids:
        return None
    matches = [row for row in auds if row.group_id in ids]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    now = datetime.utcnow()
    open_ones = [row for row in matches if paper_window(paper, now, row) == "open"]
    if open_ones:
        return open_ones[0]
    waiting = [row for row in matches if paper_window(paper, now, row) == "waiting"]
    if waiting:
        return min(waiting, key=lambda row: paper_opens_at(paper, row) or now)
    return matches[0]


def paper_visible_to(paper: Paper, user: User) -> bool:
    if not paper_released(paper):
        return False
    auds = list(getattr(paper, "audiences", None) or [])
    if not auds:
        return True
    return audience_for_user(paper, user) is not None


def paper_opens_at(paper: Paper, audience=None) -> datetime | None:
    if audience is not None and getattr(audience, "opens_at", None):
        return audience.opens_at
    return getattr(paper, "opens_at", None) or getattr(paper, "released_at", None)


def paper_closes_at(paper: Paper, audience=None) -> datetime | None:
    end = getattr(audience, "closes_at", None) if audience is not None else None
    if end:
        return end
    end = getattr(paper, "closes_at", None)
    if end:
        return end
    start = paper_opens_at(paper, audience)
    minutes = int(getattr(paper, "duration_minutes", 0) or 0)
    if minutes <= 0 or not start:
        return None
    return start + timedelta(minutes=minutes)


def paper_ends_at(paper: Paper, audience=None) -> datetime | None:
    return paper_closes_at(paper, audience)


def paper_window(paper: Paper, now: datetime | None = None, audience=None) -> str:
    if not paper_released(paper):
        return "unpublished"
    now = now or datetime.utcnow()
    start = paper_opens_at(paper, audience)
    end = paper_closes_at(paper, audience)
    if start and now < start:
        return "waiting"
    if end and now >= end:
        return "closed"
    return "open"


def paper_can_enter(paper: Paper, audience=None) -> bool:
    return paper_window(paper, audience=audience) == "open"


def paper_remaining_sec(paper: Paper, now: datetime | None = None, audience=None) -> int | None:
    now = now or datetime.utcnow()
    state = paper_window(paper, now, audience)
    if state == "waiting":
        start = paper_opens_at(paper, audience)
        if not start:
            return None
        return max(0, int((start - now).total_seconds()))
    end = paper_closes_at(paper, audience)
    if end is None:
        return None
    return max(0, int((end - now).total_seconds()))


def paper_expired(paper: Paper, now: datetime | None = None, audience=None) -> bool:
    return paper_window(paper, now, audience) == "closed"


def paper_all_windows_closed(paper: Paper, now: datetime | None = None) -> bool:
    auds = list(getattr(paper, "audiences", None) or [])
    if not auds:
        return paper_window(paper, now) == "closed"
    return all(paper_window(paper, now, row) == "closed" for row in auds)


def paper_can_start_grade(paper: Paper, now: datetime | None = None) -> bool:
    if not paper_released(paper):
        return False
    auds = list(getattr(paper, "audiences", None) or [])
    ends = [paper_closes_at(paper, row) for row in auds] if auds else [paper_closes_at(paper)]
    if not any(ends):
        return True
    return paper_all_windows_closed(paper, now)


def paper_flow(paper: Paper) -> dict[str, Any]:
    released = paper_released(paper)
    grading = bool(getattr(paper, "grading_started_at", None))
    scores_out = bool(getattr(paper, "scores_released_at", None))
    window = paper_window(paper)
    if not released:
        label = "未发布"
    elif window == "waiting":
        label = "未开考"
    elif grading and scores_out:
        label = "已发成绩"
    elif grading:
        label = "评分中"
    elif window == "closed":
        label = "已截止"
    else:
        label = "答题中"
    return {
        "released": released,
        "grading": grading,
        "scores_released": scores_out,
        "window": window,
        "can_enter": window == "open",
        "can_start_grade": paper_can_start_grade(paper),
        "flow_label": label,
    }


def timing_fields(paper: Paper, audience=None) -> dict[str, Any]:
    now = datetime.utcnow()
    window = paper_window(paper, now, audience)
    start = paper_opens_at(paper, audience)
    end = paper_closes_at(paper, audience)
    remaining = paper_remaining_sec(paper, now, audience)
    duration = int(getattr(paper, "duration_minutes", 0) or 0)
    if start and end:
        duration = max(duration, int((end - start).total_seconds() // 60))
    return {
        "duration_minutes": duration,
        "remaining_sec": remaining if window in {"waiting", "open"} else 0 if window == "closed" else None,
        "opens_in_sec": remaining if window == "waiting" else None,
        "timed": bool(end),
        "expired": window == "closed",
        "opens_at": utc_iso(start),
        "closes_at": utc_iso(end),
        **paper_flow(paper),
        "window": window,
        "can_enter": window == "open",
    }


def paper_scripts(db: Session, paper: Paper) -> list[dict[str, Any]]:
    slugs = json.loads(paper.slugs_json)
    rows = []
    for attempt in paper.attempts:
        ctx = score_context(db, attempt.user_id, "paper", attempt.id, slugs)
        rows.append(
            {
                "attempt_id": attempt.id,
                "status": "缺考" if attempt.status == "absent" else "已交卷" if attempt.status == "submitted" else "未交卷",
                "submitted": attempt.status in {"submitted", "absent"},
                "pending": int(ctx["pending"]),
                "score": ctx["score"],
                "max_score": ctx["max_score"],
                "complete": attempt.status in {"submitted", "absent"}
                and int(ctx["pending"]) == 0
                and bool(paper.grading_started_at),
            }
        )
    rows.sort(key=lambda r: hashlib.sha256(f"{paper.id}:{r['attempt_id']}".encode()).hexdigest())
    for i, row in enumerate(rows, 1):
        row["label"] = f"答卷 {i}"
        row["rank"] = None
        row["rank_total"] = sum(1 for r in rows if r["complete"])
    complete = sorted(
        [r for r in rows if r["complete"]],
        key=lambda r: (-float(r["score"] or 0), r["label"]),
    )
    rank_of = {r["attempt_id"]: i + 1 for i, r in enumerate(complete)}
    for row in rows:
        row["rank"] = rank_of.get(row["attempt_id"])
    return rows


def paper_ranking(db: Session, paper: Paper, named: bool = True) -> list[dict[str, Any]]:
    if not named:
        return paper_scripts(db, paper)
    slugs = json.loads(paper.slugs_json)
    rows = []
    for attempt in paper.attempts:
        ctx = score_context(db, attempt.user_id, "paper", attempt.id, slugs)
        student = attempt.user
        rows.append(
            {
                "attempt_id": attempt.id,
                "user_id": attempt.user_id,
                "name": teacher_label(student),
                "status": "缺考" if attempt.status == "absent" else "已交卷" if attempt.status == "submitted" else "未交卷",
                "submitted": attempt.status in {"submitted", "absent"},
                "pending": int(ctx["pending"]),
                "score": ctx["score"],
                "max_score": ctx["max_score"],
                "complete": attempt.status in {"submitted", "absent"}
                and int(ctx["pending"]) == 0
                and bool(paper.grading_started_at),
            }
        )
    complete = sorted(
        [r for r in rows if r["complete"]],
        key=lambda r: (-float(r["score"] or 0), r.get("name") or ""),
    )
    rank_of = {r["user_id"]: i + 1 for i, r in enumerate(complete)}
    total = len(complete)
    for row in rows:
        row["rank"] = rank_of.get(row.get("user_id"))
        row["rank_total"] = total
    rows.sort(key=lambda r: (0 if r["complete"] else 1, -(float(r["score"] or 0) if r["submitted"] else -1), r.get("name") or ""))
    return rows
