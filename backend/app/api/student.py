from __future__ import annotations

import json
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import CHALLENGE_SIZE, DIFFICULTIES, GRADE_LABELS, SUBJECTS
from ..db import get_db
from ..deps import get_current_user
from ..models import ChallengeRun, Paper, PaperAttempt, User
from ..schemas import ChallengeStartIn, DraftIn
from ..services.answers import item_state, save_draft, score_context, submit_item
from ..services.bank import BankError, bank
from ..services.timing import timing_fields

router = APIRouter(prefix="/api", tags=["student"])


@router.get("/home")
def home(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    grade = user.grade if user.role == "student" else None
    counts = bank.counts_by_subject(grade)
    subjects = [
        {"id": key, "name": name, "count": counts.get(key, 0)}
        for key, name in SUBJECTS.items()
    ]
    run = db.scalar(
        select(ChallengeRun)
        .where(ChallengeRun.user_id == user.id, ChallengeRun.status == "active")
        .order_by(ChallengeRun.id.desc())
    )
    papers = db.scalars(select(Paper).order_by(Paper.id.desc())).all()
    paper_out = []
    for paper in papers:
        attempt = db.scalar(
            select(PaperAttempt).where(PaperAttempt.paper_id == paper.id, PaperAttempt.user_id == user.id)
        )
        paper_out.append(
            {
                "id": paper.id,
                "title": paper.title,
                "subject": paper.subject,
                "subject_name": SUBJECTS.get(paper.subject, paper.subject),
                "kind": paper.kind,
                "status": attempt.status if attempt else "未开始",
                "attempt_id": attempt.id if attempt else None,
                **timing_fields(paper),
            }
        )
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "grade": user.grade,
            "display_name": user.display_name or user.username,
        },
        "subjects": subjects,
        "grades": [{"id": k, "name": v} for k, v in GRADE_LABELS.items()],
        "difficulties": [{"id": k, "name": v} for k, v in DIFFICULTIES.items()],
        "challenge_size": CHALLENGE_SIZE,
        "challenge": None
        if not run
        else {
            "id": run.id,
            "subject": run.subject,
            "index": run.current_index,
            "total": len(json.loads(run.slugs_json)),
        },
        "papers": paper_out,
    }


@router.get("/scores")
def my_scores(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    runs = db.scalars(
        select(ChallengeRun).where(ChallengeRun.user_id == user.id).order_by(ChallengeRun.id.desc())
    ).all()
    attempts = db.scalars(
        select(PaperAttempt).where(PaperAttempt.user_id == user.id).order_by(PaperAttempt.id.desc())
    ).all()
    challenges = []
    for run in runs:
        slugs = json.loads(run.slugs_json)
        challenges.append(
            {
                "id": run.id,
                "kind": "闯关",
                "title": SUBJECTS.get(run.subject) or "综合闯关",
                "status": "进行中" if run.status == "active" else "已完成",
                "href": f"/challenge/{run.id}/result" if run.status == "done" else f"/play/challenge/{run.id}/{run.current_index}",
                **score_context(db, user.id, "challenge", run.id, slugs),
            }
        )
    papers = []
    for attempt in attempts:
        paper = attempt.paper
        slugs = json.loads(paper.slugs_json)
        papers.append(
            {
                "id": attempt.id,
                "kind": "试卷",
                "title": paper.title,
                "status": "已交卷" if attempt.status == "submitted" else "未交卷",
                "href": f"/paper/{attempt.id}",
                **score_context(db, user.id, "paper", attempt.id, slugs),
            }
        )
    return {"challenges": challenges, "papers": papers}


@router.get("/scores/by-tag")
def my_scores_by_tag(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return scores_by_tag(db, [user], for_self=True)


def _slugs(run: ChallengeRun) -> list[str]:
    return json.loads(run.slugs_json)


def _challenge_rows(
    subject: str | None,
    grade: int | None,
    difficulty: str | None,
    tags: list[str] | None = None,
) -> tuple[list, list[str]]:
    rows = bank.list(subject=subject or None, grade=grade, difficulty=difficulty or None)
    topics = sorted({t for i in rows for t in i.tags})
    need = [t for t in (tags or []) if t]
    if need:
        rows = [i for i in rows if all(t in i.tags for t in need)]
    return rows, topics


@router.get("/challenge/pool")
def challenge_pool(
    subject: str | None = None,
    grade: int | None = None,
    difficulty: str | None = None,
    tags: list[str] = Query(default=[]),
    user: User = Depends(get_current_user),
) -> dict:
    rows, topics = _challenge_rows(subject, grade, difficulty, tags)
    return {"count": len(rows), "take": min(CHALLENGE_SIZE, len(rows)), "topics": topics}


@router.post("/challenge/start")
def start_challenge(
    body: ChallengeStartIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    active = db.scalar(
        select(ChallengeRun).where(ChallengeRun.user_id == user.id, ChallengeRun.status == "active")
    )
    if body.resume:
        if not active:
            raise HTTPException(400, "没有进行中的闯关")
        return {"id": active.id, "index": active.current_index, "total": len(_slugs(active))}
    if body.subject and body.subject not in SUBJECTS:
        raise HTTPException(400, "没有这个科目")
    if active:
        active.status = "done"
        active.finished_at = datetime.utcnow()
    rows, _topics = _challenge_rows(body.subject, body.grade, body.difficulty, body.tags)
    if not rows:
        raise HTTPException(400, "这个组合下还没有题")
    random.shuffle(rows)
    chosen = rows[:CHALLENGE_SIZE]
    subject = body.subject or (chosen[0].subject if len({i.subject for i in chosen}) == 1 else "*")
    run = ChallengeRun(
        user_id=user.id,
        subject=subject,
        grade=body.grade,
        difficulty=body.difficulty,
        slugs_json=json.dumps([i.slug for i in chosen], ensure_ascii=False),
        current_index=0,
        status="active",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"id": run.id, "index": 0, "total": len(chosen)}


@router.get("/challenge/{run_id}")
def get_challenge(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    run = db.get(ChallengeRun, run_id)
    if not run or run.user_id != user.id:
        raise HTTPException(404, "找不到这次闯关")
    slugs = _slugs(run)
    return {
        "id": run.id,
        "subject": run.subject,
        "subject_name": SUBJECTS.get(run.subject) or "综合闯关",
        "index": run.current_index,
        "total": len(slugs),
        "status": run.status,
        "slugs": slugs,
        **score_context(db, user.id, "challenge", run.id, slugs),
    }


@router.get("/challenge/{run_id}/item/{index}")
def challenge_item(
    run_id: int, index: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    run = db.get(ChallengeRun, run_id)
    if not run or run.user_id != user.id:
        raise HTTPException(404, "找不到这次闯关")
    slugs = _slugs(run)
    if index < 0 or index >= len(slugs):
        raise HTTPException(404, "没有这一题")
    try:
        item = bank.get(slugs[index])
    except BankError as exc:
        raise HTTPException(404, str(exc)) from exc
    reveal = True
    payload = item_state(db, user.id, "challenge", run.id, item, reveal=reveal)
    payload["index"] = index
    payload["total"] = len(slugs)
    payload["run_id"] = run.id
    payload["run_status"] = run.status
    return payload


@router.put("/challenge/{run_id}/item/{index}/draft")
def challenge_draft(
    run_id: int,
    index: int,
    body: DraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(ChallengeRun, run_id)
    if not run or run.user_id != user.id or run.status != "active":
        raise HTTPException(400, "这次闯关已经结束")
    slugs = _slugs(run)
    item = bank.get(slugs[index])
    save_draft(db, user.id, "challenge", run.id, item, body.parts)
    db.commit()
    return {"ok": True}


@router.post("/challenge/{run_id}/item/{index}/submit")
def challenge_submit(
    run_id: int,
    index: int,
    body: DraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(ChallengeRun, run_id)
    if not run or run.user_id != user.id or run.status != "active":
        raise HTTPException(400, "这次闯关已经结束")
    slugs = _slugs(run)
    item = bank.get(slugs[index])
    submit_item(db, user.id, "challenge", run.id, item, body.parts)
    if index >= run.current_index:
        run.current_index = min(index + 1, len(slugs))
    done = run.current_index >= len(slugs)
    if done:
        run.status = "done"
        run.finished_at = datetime.utcnow()
    db.commit()
    return {
        "ok": True,
        "next": None if done else run.current_index,
        "done": done,
        **item_state(db, user.id, "challenge", run.id, item, reveal=True),
    }
