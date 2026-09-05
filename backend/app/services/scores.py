from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import DIFFICULTIES, SUBJECTS, TYPES, grade_label
from ..models import ChallengeRun, ItemAnswer, PaperAttempt, User
from .answers import scores_visible_for_paper
from .bank import Item, bank
from .groups import teacher_label


def _points(row: ItemAnswer) -> float | None:
    if row.status == "overridden":
        return float(row.override_score or 0)
    if row.status == "graded":
        return float(row.score or 0)
    return None


def _bundle_summary(parts: list[ItemAnswer]) -> dict[str, Any]:
    score = 0.0
    maximum = 0.0
    pending = 0
    graded = False
    latest = None
    for row in parts:
        maximum += row.max_score or 0
        pts = _points(row)
        if pts is not None:
            score += pts
            graded = True
        elif row.status == "pending":
            pending += 1
        stamp = row.updated_at or row.submitted_at
        if stamp and (latest is None or stamp > latest):
            latest = stamp
    if pending and graded:
        status = "部分待评"
    elif pending:
        status = "待评分"
    elif graded:
        status = "已评分"
    else:
        status = "已交"
    return {
        "score": round(score, 2) if graded else None,
        "max_score": round(maximum, 2),
        "pending": pending,
        "status": status,
        "graded": graded,
        "ratio": (score / maximum) if graded and maximum else -1,
        "latest": latest,
        "context_type": parts[0].context_type,
        "context_id": parts[0].context_id,
    }


def _source_and_href(db: Session, context_type: str, context_id: int, for_self: bool) -> tuple[str, str | None]:
    if context_type == "challenge":
        run = db.get(ChallengeRun, context_id)
        name = (SUBJECTS.get(run.subject) or "综合闯关") if run else "闯关"
        label = f"闯关 · {name}"
        href = None
        if for_self and run:
            href = (
                f"/challenge/{run.id}/result"
                if run.status == "done"
                else f"/play/challenge/{run.id}/{run.current_index}"
            )
        return label, href
    attempt = db.get(PaperAttempt, context_id)
    title = attempt.paper.title if attempt and attempt.paper else "试卷"
    href = f"/paper/{attempt.id}" if for_self and attempt else None
    return f"试卷 · {title}", href


def _item_row(
    user: User, item: Item, summary: dict[str, Any], source: str, href: str | None, *, for_self: bool
) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "student": user.username if for_self else teacher_label(user),
        "slug": item.slug,
        "title": item.title or item.slug,
        "subject": item.subject,
        "subject_name": SUBJECTS.get(item.subject, item.subject),
        "type": item.type,
        "type_name": TYPES.get(item.type, item.type),
        "difficulty": item.difficulty,
        "difficulty_name": DIFFICULTIES.get(item.difficulty, item.difficulty),
        "grade": item.grade,
        "grade_name": grade_label(item.grade),
        "tags": list(item.tags),
        "score": summary["score"] if summary["score"] is not None else 0,
        "max_score": summary["max_score"],
        "pending": summary["pending"],
        "status": summary["status"],
        "source": source,
        "href": href,
    }


def _chip(kind: str, key: str, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    score = sum(r["score"] for r in rows)
    maximum = sum(r["max_score"] for r in rows)
    pending = sum(r["pending"] for r in rows)
    return {
        "id": key,
        "name": name,
        "kind": kind,
        "score": round(score, 2),
        "max_score": round(maximum, 2),
        "pending": pending,
        "count": len(rows),
    }


def scores_by_tag(db: Session, users: list[User], for_self: bool) -> dict[str, Any]:
    if not users:
        return {
            "students": [],
            "subjects": [],
            "types": [],
            "difficulties": [],
            "grades": [],
            "topics": [],
            "items": [],
        }
    user_map = {u.id: u for u in users}
    rows = db.scalars(
        select(ItemAnswer).where(ItemAnswer.user_id.in_(list(user_map)), ItemAnswer.status != "draft")
    ).all()
    bundles: dict[tuple[int, str, str, int], list[ItemAnswer]] = defaultdict(list)
    for row in rows:
        bundles[(row.user_id, row.item_slug, row.context_type, row.context_id)].append(row)

    best: dict[tuple[int, str], dict[str, Any]] = {}
    for (user_id, slug, context_type, context_id), parts in bundles.items():
        if context_type == "paper":
            attempt = db.get(PaperAttempt, context_id)
            paper = attempt.paper if attempt else None
            if not scores_visible_for_paper(paper):
                continue
        summary = _bundle_summary(parts)
        key = (user_id, slug)
        prev = best.get(key)
        if prev is None:
            best[key] = {**summary, "context_type": context_type, "context_id": context_id}
            continue
        better = summary["ratio"] > prev["ratio"]
        same = summary["ratio"] == prev["ratio"] and (summary["latest"] or 0) > (prev["latest"] or 0)
        if better or same:
            best[key] = {**summary, "context_type": context_type, "context_id": context_id}

    items: list[dict[str, Any]] = []
    for (user_id, slug), summary in best.items():
        try:
            item = bank.get(slug)
        except Exception:
            continue
        user = user_map[user_id]
        source, href = _source_and_href(db, summary["context_type"], summary["context_id"], for_self)
        items.append(_item_row(user, item, summary, source, href, for_self=for_self))
    items.sort(key=lambda r: (r["student"], r["subject_name"], r["title"]))

    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_diff: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_grade: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in items:
        by_subject[row["subject"]].append(row)
        by_type[row["type"]].append(row)
        by_diff[row["difficulty"]].append(row)
        if row["grade"]:
            by_grade[str(row["grade"])].append(row)
        for tag in row["tags"]:
            by_topic[tag].append(row)

    return {
        "students": [{"id": u.id, "name": u.username if for_self else teacher_label(u)} for u in users],
        "subjects": [_chip("subject", k, SUBJECTS.get(k, k), v) for k, v in sorted(by_subject.items(), key=lambda x: SUBJECTS.get(x[0], x[0]))],
        "types": [_chip("type", k, TYPES.get(k, k), v) for k, v in sorted(by_type.items(), key=lambda x: TYPES.get(x[0], x[0]))],
        "difficulties": [_chip("difficulty", k, DIFFICULTIES.get(k, k), v) for k, v in sorted(by_diff.items(), key=lambda x: DIFFICULTIES.get(x[0], x[0]))],
        "grades": [_chip("grade", k, grade_label(int(k)), v) for k, v in sorted(by_grade.items(), key=lambda x: int(x[0]))],
        "topics": [_chip("topic", k, k, v) for k, v in sorted(by_topic.items(), key=lambda x: x[0])],
        "items": items,
    }
