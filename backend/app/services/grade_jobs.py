from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import DateTime, Integer, String, Text, and_, exists, or_, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..db import Base
from ..models import ItemAnswer, Paper, PaperAttempt
from .bank import Item, Part

log = logging.getLogger(__name__)


class GradeJob(Base):
    """One durable, replaceable generation per answer; written with the answer transaction."""
    __tablename__ = "grade_jobs"

    answer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    item_json: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    photos_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    score_json: Mapped[str] = mapped_column(Text, nullable=False)
    identity_json: Mapped[str] = mapped_column(Text, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(32), nullable=True)


def _score_state(row: ItemAnswer) -> str:
    return json.dumps([row.score, row.llm_json, row.llm_comment, row.override_score,
                       row.override_comment, row.override_by], ensure_ascii=False)


def enqueue(db: Session, row: ItemAnswer, item: Item, *, retry: bool = False) -> bool:
    """Record work in the caller's transaction. A rollback leaves no dispatchable work."""
    if not ((row.status == "pending" and row.override_score is None) or
            (retry and row.status == "overridden" and row.override_score is not None)):
        return False
    db.flush()
    data = json.dumps(asdict(item), ensure_ascii=False, sort_keys=True)
    score_state = _score_state(row)
    identity = json.dumps([row.user_id, row.context_type, row.context_id, row.item_slug,
                           row.part_id, row.max_score], ensure_ascii=False)
    job = db.get(GradeJob, row.id)
    if (job is not None and not retry and job.item_json == data
            and job.value_json == row.value_json and job.photos_json == row.photos_json
            and job.submitted_at == row.submitted_at and job.score_json == score_state
            and job.identity_json == identity):
        return False
    if job is None:
        job = GradeJob(answer_id=row.id)
        db.add(job)
    job.generation = uuid.uuid4().hex
    job.state = "queued"
    job.item_json = data
    job.value_json = row.value_json
    job.photos_json = row.photos_json
    job.submitted_at = row.submitted_at
    job.score_json = score_state
    job.identity_json = identity
    job.lease_until = None
    job.claim_token = None
    return True


def _claim(db: Session) -> tuple[int, str, str] | None:
    now = datetime.utcnow()
    candidate = db.execute(
        select(GradeJob.answer_id, GradeJob.generation).where(
            (GradeJob.state == "queued") | ((GradeJob.state == "running") & (GradeJob.lease_until < now))
        ).order_by(GradeJob.answer_id).limit(1)
    ).first()
    if not candidate:
        return None
    answer_id, generation = candidate
    token = uuid.uuid4().hex
    claimed = db.execute(update(GradeJob).where(
        GradeJob.answer_id == answer_id, GradeJob.generation == generation,
        (GradeJob.state == "queued") | ((GradeJob.state == "running") & (GradeJob.lease_until < now)),
    ).values(state="running", claim_token=token, lease_until=now + timedelta(minutes=2)))
    db.commit()
    return (answer_id, generation, token) if claimed.rowcount else None


def _conditions(answer_id, generation, token, value_json, photos_json, submitted_at, score_state, identity):
    score, old_json, old_comment, override, override_comment, override_by = json.loads(score_state)
    user_id, context_type, context_id, item_slug, part_id, max_score = json.loads(identity)
    live_job = exists(select(GradeJob.answer_id).where(
        GradeJob.answer_id == answer_id, GradeJob.generation == generation,
        GradeJob.state == "running", GradeJob.claim_token == token))
    paper_open = exists(select(PaperAttempt.id).join(Paper, Paper.id == PaperAttempt.paper_id).where(
        PaperAttempt.id == ItemAnswer.context_id, PaperAttempt.user_id == ItemAnswer.user_id,
        PaperAttempt.status == "submitted", Paper.grading_started_at.is_not(None),
        Paper.scores_released_at.is_(None)))
    return [ItemAnswer.id == answer_id, live_job,
            ItemAnswer.status == ("overridden" if override is not None else "pending"),
            ItemAnswer.user_id == user_id, ItemAnswer.context_type == context_type,
            ItemAnswer.context_id == context_id, ItemAnswer.item_slug == item_slug,
            ItemAnswer.part_id == part_id, ItemAnswer.max_score == max_score,
            ItemAnswer.value_json == value_json, ItemAnswer.photos_json == photos_json,
            ItemAnswer.submitted_at == submitted_at, ItemAnswer.submitted_at.is_not(None),
            ItemAnswer.score == score, ItemAnswer.llm_json == old_json,
            ItemAnswer.llm_comment == old_comment, ItemAnswer.override_score == override,
            ItemAnswer.override_comment == override_comment, ItemAnswer.override_by == override_by,
            or_(ItemAnswer.context_type == "challenge", and_(ItemAnswer.context_type == "paper", paper_open))]


def _run_one(session_factory) -> bool:
    from .grade import load_value
    from .llm import LLM_FAIL_PREFIX, grade_part_attempt

    with session_factory() as db:
        claim = _claim(db)
        if not claim:
            return False
        answer_id, generation, token = claim
        job = db.get(GradeJob, answer_id)
        if not job or job.generation != generation:
            return True
        # Copy the immutable input before releasing the database while the model runs.
        item_json, value_json, photos_json = job.item_json, job.value_json, job.photos_json
        submitted_at, score_state, identity = job.submitted_at, job.score_json, job.identity_json
        conditions = _conditions(answer_id, generation, token, value_json, photos_json,
                                 submitted_at, score_state, identity)
        if db.scalar(select(ItemAnswer.id).where(*conditions)) is None:
            db.execute(update(GradeJob).where(GradeJob.answer_id == answer_id,
                GradeJob.generation == generation, GradeJob.claim_token == token,
                GradeJob.state == "running").values(state="cancelled", claim_token=None, lease_until=None))
            db.commit()
            return True
        db.rollback()
    stopped = threading.Event()

    def heartbeat() -> None:
        while not stopped.wait(30):
            try:
                with session_factory.begin() as db:
                    renewed = db.execute(update(GradeJob).where(
                        GradeJob.answer_id == answer_id, GradeJob.generation == generation,
                        GradeJob.state == "running", GradeJob.claim_token == token,
                    ).values(lease_until=datetime.utcnow() + timedelta(minutes=2)))
                    if not renewed.rowcount:
                        return
            except Exception:
                log.exception("评分任务续期失败")

    pulse = threading.Thread(target=heartbeat, name="llm-grade-lease", daemon=True)
    pulse.start()
    try:
        raw = json.loads(item_json)
        raw["parts"] = [Part(**part) for part in raw["parts"]]
        item = Item(**raw)
        user_id, context_type, context_id, item_slug, part_id, max_score = json.loads(identity)
        part = next(p for p in item.parts if p.id == part_id)
        photos = json.loads(photos_json or "[]")
        if not isinstance(photos, list) or any(not isinstance(p, str) for p in photos):
            raise ValueError("作答图片记录无效，请人工评分")
        result, error, _retryable = grade_part_attempt(item, part, str(load_value(value_json) or ""), photos)
    except Exception as exc:
        result, error = None, str(exc)
    finally:
        stopped.set()
        pulse.join()

    with session_factory() as db:
        # The conditional update makes comparison and application indivisible even if
        # a teacher or a new submission changes the answer while the model runs.
        override = json.loads(score_state)[3]
        conditions = _conditions(answer_id, generation, token, value_json, photos_json,
                                 submitted_at, score_state, identity)
        if result:
            values = dict(score=float(result["total"]), status="overridden" if override is not None else "graded", graded_at=datetime.utcnow(),
                          llm_comment=result.get("comment") or "", llm_json=json.dumps(result, ensure_ascii=False))
        elif override is not None:
            values = dict(status="overridden")
        else:
            values = dict(status="pending", llm_comment=LLM_FAIL_PREFIX + (error or "未知原因"))
        applied = db.execute(update(ItemAnswer).where(*conditions).values(**values))
        db.execute(update(GradeJob).where(GradeJob.answer_id == answer_id,
                                         GradeJob.generation == generation, GradeJob.state == "running",
                                         GradeJob.claim_token == token)
                   .values(state=("done" if result else "failed") if applied.rowcount else "cancelled", lease_until=None, claim_token=None))
        db.commit()
    return True


_started = False
_start_lock = threading.Lock()


def _restore_legacy_pending(session_factory) -> None:
    """Give pending answers from versions without durable jobs a durable record."""
    from .snapshots import context_item

    with session_factory.begin() as db:
        rows = db.scalars(select(ItemAnswer).where(
            ItemAnswer.status == "pending",
            ItemAnswer.override_score.is_(None),
            ~exists(select(GradeJob.answer_id).where(GradeJob.answer_id == ItemAnswer.id)),
        )).all()
        for row in rows:
            item = context_item(db, row.context_type, row.context_id, row.item_slug)
            if item is not None:
                enqueue(db, row, item)


def start_worker() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        _started = True

    def loop() -> None:
        from ..config import llm_configured
        from ..db import SessionLocal
        try:
            _restore_legacy_pending(SessionLocal)
        except Exception:
            log.exception("恢复旧版待评分作答失败")
        while True:
            try:
                if not llm_configured() or not _run_one(SessionLocal):
                    time.sleep(2)
            except Exception:
                log.exception("评分任务处理失败")
                time.sleep(2)

    threading.Thread(target=loop, name="llm-grade", daemon=True).start()
