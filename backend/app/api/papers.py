from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import SUBJECTS
from ..db import get_db, reserve_write
from ..deps import get_current_user
from ..models import Paper, PaperAttempt, User
from ..schemas import DraftIn
from ..services.answers import (
    item_state,
    paper_save_progress,
    save_draft,
    score_context,
    scores_visible_for_paper,
    submit_item,
)
from ..services.snapshots import paper_item as snapshot_item
from ..services.paper_layout import heading_for_slug, paper_layout
from ..services.timing import (
    audience_for_user,
    paper_expired,
    paper_released,
    paper_visible_to,
    paper_window,
    timing_fields,
)

router = APIRouter(prefix="/api/papers", tags=["papers"])


def _existing_attempt(db: Session, paper: Paper, user: User) -> PaperAttempt | None:
    return db.scalar(
        select(PaperAttempt).where(PaperAttempt.paper_id == paper.id, PaperAttempt.user_id == user.id)
    )


def _deny_before_open(paper: Paper, user: User) -> None:
    if not paper_released(paper):
        raise HTTPException(403, "这份试卷还没发布")
    if not paper_visible_to(paper, user):
        raise HTTPException(403, "这份试卷不是给你这个分组的")
    if paper_window(paper, audience=audience_for_user(paper, user)) == "waiting":
        raise HTTPException(403, "还没到答题时间，现在看不到题目")


def _get_attempt(db: Session, paper: Paper, user: User) -> PaperAttempt:
    attempt = _existing_attempt(db, paper, user)
    if attempt:
        return attempt
    attempt = PaperAttempt(paper_id=paper.id, user_id=user.id, status="draft")
    db.add(attempt)
    db.flush()
    return attempt


def _sheet(db: Session, user_id: int, attempt_id: int, slugs: list[str]) -> list[dict]:
    progress = paper_save_progress(db, user_id, attempt_id, slugs)
    saved = set(progress["saved_slugs"])
    return [{"n": i + 1, "slug": slug, "saved": slug in saved} for i, slug in enumerate(slugs)]


def _mark_saved(items: list[dict], saved: set[str]) -> list[dict]:
    out = []
    for row in items:
        item = dict(row)
        item["saved"] = item.get("slug") in saved
        out.append(item)
    return out


def _force_submit(db: Session, attempt: PaperAttempt, paper: Paper) -> None:
    if attempt.status in {"submitted", "absent"}:
        return
    slugs = json.loads(paper.slugs_json)
    for slug in slugs:
        item = snapshot_item(paper, slug)
        if item:
            submit_item(
                db,
                attempt.user_id,
                "paper",
                attempt.id,
                item,
                None,
                grade=False,
            )
    attempt.status = "submitted"
    attempt.submitted_at = datetime.utcnow()


def _maybe_expire(db: Session, attempt: PaperAttempt, paper: Paper) -> None:
    if attempt.status in {"submitted", "absent"}:
        return
    aud = audience_for_user(paper, attempt.user)
    if paper_expired(paper, audience=aud):
        reserve_write(db)
        db.refresh(attempt)
        db.refresh(paper)
        if attempt.status in {"submitted", "absent"} or not paper_expired(paper, audience=audience_for_user(paper, attempt.user)):
            return
        _force_submit(db, attempt, paper)
        db.commit()
        db.refresh(attempt)


def _payload(db: Session, paper: Paper, attempt: PaperAttempt, user: User) -> dict:
    slugs = json.loads(paper.slugs_json)
    progress = paper_save_progress(db, user.id, attempt.id, slugs)
    saved = set(progress["saved_slugs"])
    sections = []
    for row in paper_layout(paper):
        items = [item.summary() for s in row["slugs"] if (item := snapshot_item(paper, s))]
        sections.append({"heading": row["heading"], "items": _mark_saved(items, saved)})
    ctx = score_context(db, user.id, "paper", attempt.id, slugs)
    visible = scores_visible_for_paper(paper)
    if not visible:
        ctx = {**ctx, "score": None, "pending": 0}
    aud = audience_for_user(paper, user)
    return {
        "attempt_id": attempt.id,
        "paper_id": paper.id,
        "title": paper.title,
        "kind": paper.kind,
        "allow_revise": paper.allow_revise,
        "status": attempt.status,
        "slugs": slugs,
        "sheet": _sheet(db, user.id, attempt.id, slugs),
        "items": _mark_saved([item.summary() for s in slugs if (item := snapshot_item(paper, s))], saved),
        "sections": sections,
        **timing_fields(paper, aud),
        **ctx,
        **progress,
        "scores_visible": visible,
        "can_submit": attempt.status not in {"submitted", "absent"} and bool(progress["all_saved"]),
        "subject": paper.subject,
        "subject_name": SUBJECTS.get(paper.subject, paper.subject),
    }


@router.post("/{paper_id}/open")
def open_paper(paper_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    reserve_write(db)
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "找不到这份试卷")
    _deny_before_open(paper, user)
    existing = _existing_attempt(db, paper, user)
    if existing and existing.status == "absent":
        raise HTTPException(403, "这次记缺考，不能再进卷")
    aud = audience_for_user(paper, user)
    if paper_window(paper, audience=aud) == "closed":
        if not existing:
            raise HTTPException(403, "答题已经结束")
        _maybe_expire(db, existing, paper)
        return _payload(db, paper, existing, user)
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
    _deny_before_open(paper, user)
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
    _deny_before_open(paper, user)
    _maybe_expire(db, attempt, paper)
    slugs = json.loads(paper.slugs_json)
    if slug not in slugs:
        raise HTTPException(404, "这份卷里没有这道题")
    item = snapshot_item(paper, slug)
    if not item:
        raise HTTPException(404, "试卷中的这道题不可用")
    reveal = scores_visible_for_paper(paper)
    payload = item_state(db, user.id, "paper", attempt.id, item, reveal=reveal)
    index = slugs.index(slug)
    progress = paper_save_progress(db, user.id, attempt.id, slugs)
    payload["attempt_id"] = attempt.id
    payload["index"] = index
    payload["total"] = len(slugs)
    payload["prev_slug"] = slugs[index - 1] if index > 0 else None
    payload["next_slug"] = slugs[index + 1] if index + 1 < len(slugs) else None
    payload["section_heading"] = heading_for_slug(paper, slug)
    aud = audience_for_user(paper, user)
    payload["locked"] = (attempt.status in {"submitted", "absent"} and not paper.allow_revise) or paper_expired(paper, audience=aud)
    payload["exam"] = paper.kind == "exam" and attempt.status not in {"submitted", "absent"}
    payload["sheet"] = _sheet(db, user.id, attempt.id, slugs)
    payload["scores_visible"] = reveal
    payload.update(progress)
    payload.update(timing_fields(paper, aud))
    return payload


@router.put("/attempts/{attempt_id}/item/{slug}/draft")
def paper_draft(
    attempt_id: int,
    slug: str,
    body: DraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    reserve_write(db)
    attempt = db.get(PaperAttempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "找不到这份答卷")
    paper = attempt.paper
    _deny_before_open(paper, user)
    _maybe_expire(db, attempt, paper)
    if paper.grading_started_at or paper.scores_released_at:
        raise HTTPException(400, "试卷已开始评分，不能修改答卷")
    if attempt.status in {"submitted", "absent"} and not paper.allow_revise:
        raise HTTPException(400, "已经交卷了")
    if paper_expired(paper, audience=audience_for_user(paper, user)):
        raise HTTPException(400, "时间到了，已经交卷")
    item = snapshot_item(paper, slug)
    if not item:
        raise HTTPException(404, "试卷中的这道题不可用")
    save_draft(db, user.id, "paper", attempt.id, item, body.parts)
    db.commit()
    slugs = json.loads(paper.slugs_json)
    progress = paper_save_progress(db, user.id, attempt.id, slugs)
    return {"ok": True, "sheet": _sheet(db, user.id, attempt.id, slugs), **progress}


@router.post("/attempts/{attempt_id}/submit")
def paper_submit(
    attempt_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    reserve_write(db)
    attempt = db.get(PaperAttempt, attempt_id)
    if not attempt or attempt.user_id != user.id:
        raise HTTPException(404, "找不到这份答卷")
    paper = attempt.paper
    _deny_before_open(paper, user)
    if paper.grading_started_at or paper.scores_released_at:
        raise HTTPException(400, "试卷已开始评分，不能修改答卷")
    if attempt.status in {"submitted", "absent"} and not paper.allow_revise:
        raise HTTPException(400, "已经交卷了")
    slugs = json.loads(paper.slugs_json)
    expired = paper_expired(paper, audience=audience_for_user(paper, user))
    if not expired:
        progress = paper_save_progress(db, user.id, attempt.id, slugs)
        if not progress["all_saved"]:
            left = len(progress["missing_slugs"])
            raise HTTPException(400, f"还有 {left} 题没保存，不能交卷。限时到点会自动交卷。")
    for slug in slugs:
        item = snapshot_item(paper, slug)
        if item:
            submit_item(db, user.id, "paper", attempt.id, item, None, grade=False)
    attempt.status = "submitted"
    attempt.submitted_at = datetime.utcnow()
    db.commit()
    return _payload(db, paper, attempt, user)
