from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import SUBJECTS
from ..db import get_db
from ..deps import get_current_user
from ..models import Paper, PaperAttempt, User
from ..schemas import DraftIn
from ..services.answers import item_state, save_draft, score_context, submit_item
from ..services.bank import bank
from ..services.paper_layout import heading_for_slug, paper_layout
from ..services.timing import paper_expired, timing_fields

router = APIRouter(prefix="/api/papers", tags=["papers"])


def _get_attempt(db: Session, paper: Paper, user: User) -> PaperAttempt:
    attempt = db.scalar(
        select(PaperAttempt).where(PaperAttempt.paper_id == paper.id, PaperAttempt.user_id == user.id)
    )
    if attempt:
        return attempt
    attempt = PaperAttempt(paper_id=paper.id, user_id=user.id, status="draft")
    db.add(attempt)
    db.flush()
    return attempt


def _force_submit(db: Session, attempt: PaperAttempt, paper: Paper) -> None:
    if attempt.status == "submitted":
        return
    slugs = json.loads(paper.slugs_json)
    empty_zero = bool(paper.duration_minutes)
    for slug in slugs:
        if slug in bank.items:
            submit_item(
                db,
                attempt.user_id,
                "paper",
                attempt.id,
                bank.get(slug),
                None,
                empty_subjective_zero=empty_zero,
            )
    attempt.status = "submitted"
    attempt.submitted_at = datetime.utcnow()


def _maybe_expire(db: Session, attempt: PaperAttempt, paper: Paper) -> None:
    if attempt.status != "submitted" and paper_expired(paper):
        _force_submit(db, attempt, paper)
        db.commit()
        db.refresh(attempt)


def _payload(db: Session, paper: Paper, attempt: PaperAttempt, user: User) -> dict:
    slugs = json.loads(paper.slugs_json)
    sections = []
    for row in paper_layout(paper):
        items = [bank.get(s).summary() for s in row["slugs"] if s in bank.items]
        sections.append({"heading": row["heading"], "items": items})
    return {
        "attempt_id": attempt.id,
        "paper_id": paper.id,
        "title": paper.title,
        "kind": paper.kind,
        "allow_revise": paper.allow_revise,
        "status": attempt.status,
        "slugs": slugs,
        "items": [bank.get(s).summary() for s in slugs if s in bank.items],
        "sections": sections,
        **timing_fields(paper),
        **score_context(db, user.id, "paper", attempt.id, slugs),
        "subject": paper.subject,
        "subject_name": SUBJECTS.get(paper.subject, paper.subject),
    }


@router.post("/{paper_id}/open")
def open_paper(paper_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "找不到这份试卷")
    attempt = _get_attempt(db, paper, user)
    db.commit()
    db.refresh(attempt)
    _maybe_expire(db, attempt, paper)
    return _payload(db, paper, attempt, user)


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    attempt = db.get(PaperAttempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "找不到这份答卷")
    paper = attempt.paper
    _maybe_expire(db, attempt, paper)
    return _payload(db, paper, attempt, user)


@router.get("/attempts/{attempt_id}/item/{slug}")
def paper_item(
    attempt_id: int, slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    attempt = db.get(PaperAttempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "找不到这份答卷")
    paper = attempt.paper
    _maybe_expire(db, attempt, paper)
    slugs = json.loads(paper.slugs_json)
    if slug not in slugs:
        raise HTTPException(404, "这份卷里没有这道题")
    item = bank.get(slug)
    reveal = attempt.status == "submitted" or paper.kind != "exam"
    payload = item_state(db, user.id, "paper", attempt.id, item, reveal=reveal)
    index = slugs.index(slug)
    payload["attempt_id"] = attempt.id
    payload["index"] = index
    payload["total"] = len(slugs)
    payload["prev_slug"] = slugs[index - 1] if index > 0 else None
    payload["next_slug"] = slugs[index + 1] if index + 1 < len(slugs) else None
    payload["section_heading"] = heading_for_slug(paper, slug)
    payload["locked"] = (attempt.status == "submitted" and not paper.allow_revise) or paper_expired(paper)
    payload["exam"] = paper.kind == "exam" and attempt.status != "submitted"
    payload.update(timing_fields(paper))
    return payload


@router.put("/attempts/{attempt_id}/item/{slug}/draft")
def paper_draft(
    attempt_id: int,
    slug: str,
    body: DraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    attempt = db.get(PaperAttempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "找不到这份答卷")
    paper = attempt.paper
    _maybe_expire(db, attempt, paper)
    if attempt.status == "submitted" and not paper.allow_revise:
        raise HTTPException(400, "已经交卷了")
    if paper_expired(paper):
        raise HTTPException(400, "时间到了，已经交卷")
    item = bank.get(slug)
    save_draft(db, user.id, "paper", attempt.id, item, body.parts)
    db.commit()
    return {"ok": True}


@router.post("/attempts/{attempt_id}/submit")
def paper_submit(
    attempt_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    attempt = db.get(PaperAttempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "找不到这份答卷")
    paper = attempt.paper
    if attempt.status == "submitted" and not paper.allow_revise:
        raise HTTPException(400, "已经交卷了")
    empty_zero = paper_expired(paper) or bool(paper.duration_minutes and paper.kind == "exam")
    slugs = json.loads(paper.slugs_json)
    for slug in slugs:
        if slug in bank.items:
            submit_item(
                db,
                user.id,
                "paper",
                attempt.id,
                bank.get(slug),
                None,
                empty_subjective_zero=empty_zero and paper_expired(paper),
            )
    attempt.status = "submitted"
    attempt.submitted_at = datetime.utcnow()
    db.commit()
    return _payload(db, paper, attempt, user)
