from __future__ import annotations

import json
import random
import subprocess

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DEFAULT_LLM_BASE_URL, ROOT, SKILL_PATH, llm_configured, llm_from_env, llm_settings, save_llm_file
from ..constants import DIFFICULTIES, GRADE_LABELS, OBJECTIVE_TYPES, PAPER_SECTIONS, SUBJECTS, TYPES, grade_label
from ..db import get_db
from ..deps import get_admin_user, hash_password
from ..models import ChallengeRun, ItemAnswer, Paper, PaperAttempt, User
from ..schemas import AssembleIn, GradeIn, ItemEditIn, LlmSettingsIn, PasteIn, PlainItemIn, StudentIn
from ..services.access import sees_subject, scoped_subjects
from ..services.answers import score_context
from ..services.bank import BankError, bank
from ..services.ingest import item_from_editor, items_from_text, items_from_zip, plain_item, save_item
from ..services.paper_layout import fill_heading, section_spec
from ..services.llm import enqueue, grade_part_llm, list_remote_models, ping_llm, start_worker
from ..services.grade import load_value
from ..services.review import review_challenge, review_paper
from ..services.scores import scores_by_tag
from ..services.timing import paper_ranking, timing_fields

router = APIRouter(prefix="/api/parent", tags=["parent"])


def _need_subject(user: User, subject: str) -> None:
    if not sees_subject(user, subject):
        raise HTTPException(403, "这不是你负责的科目")


@router.get("/meta")
def meta(user: User = Depends(get_admin_user)) -> dict:
    allowed = scoped_subjects(user)
    return {
        "subjects": [{"id": k, "name": SUBJECTS[k]} for k in allowed],
        "all_subjects": len(allowed) == len(SUBJECTS),
        "grades": [{"id": k, "name": v} for k, v in GRADE_LABELS.items()],
        "difficulties": [{"id": k, "name": v} for k, v in DIFFICULTIES.items()],
        "types": [{"id": k, "name": v} for k, v in TYPES.items()],
        "paper_sections": [
            {
                "id": row["id"],
                "name": row["name"],
                "heading": row["heading"],
                "types": list(row["types"]),
            }
            for row in PAPER_SECTIONS
        ],
    }


@router.get("/progress")
def progress(user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    students = db.scalars(select(User).where(User.role == "student").order_by(User.id)).all()
    out = []
    for student in students:
        runs = db.scalars(
            select(ChallengeRun).where(ChallengeRun.user_id == student.id).order_by(ChallengeRun.id.desc())
        ).all()
        attempts = db.scalars(
            select(PaperAttempt).where(PaperAttempt.user_id == student.id).order_by(PaperAttempt.id.desc())
        ).all()
        run_rows = []
        score = 0.0
        maximum = 0.0
        pending = 0
        for run in runs:
            if not sees_subject(user, run.subject):
                continue
            slugs = json.loads(run.slugs_json)
            ctx = score_context(db, student.id, "challenge", run.id, slugs)
            score += float(ctx["score"])
            maximum += float(ctx["max_score"])
            pending += int(ctx["pending"])
            run_rows.append(
                {
                    "id": run.id,
                    "subject": run.subject,
                    "subject_name": SUBJECTS.get(run.subject, run.subject),
                    "status": run.status,
                    "total": len(slugs),
                    **ctx,
                }
            )
        paper_rows = []
        for attempt in attempts:
            paper = attempt.paper
            if not sees_subject(user, paper.subject):
                continue
            slugs = json.loads(paper.slugs_json)
            ctx = score_context(db, student.id, "paper", attempt.id, slugs)
            score += float(ctx["score"])
            maximum += float(ctx["max_score"])
            pending += int(ctx["pending"])
            paper_rows.append(
                {
                    "id": attempt.id,
                    "paper_id": paper.id,
                    "title": paper.title,
                    "status": attempt.status,
                    **ctx,
                }
            )
        out.append(
            {
                "id": student.id,
                "username": student.username,
                "display_name": student.display_name or student.username,
                "grade": student.grade,
                "grade_name": grade_label(student.grade),
                "score": round(score, 2),
                "max_score": round(maximum, 2),
                "pending": pending,
                "runs": run_rows,
                "papers": paper_rows,
            }
        )
    pending_rows = db.scalars(select(ItemAnswer).where(ItemAnswer.status == "pending")).all()
    pending_n = 0
    for row in pending_rows:
        item = bank.items.get(row.item_slug)
        if item and sees_subject(user, item.subject):
            pending_n += 1
    return {"students": out, "pending": pending_n}


@router.get("/scores/by-tag")
def scores_tagged(
    student_id: int | None = Query(default=None),
    user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    if student_id is not None:
        student = db.get(User, student_id)
        if not student or student.role != "student":
            raise HTTPException(404, "找不到这个学生")
        users = [student]
    else:
        users = list(db.scalars(select(User).where(User.role == "student").order_by(User.id)).all())
    data = scores_by_tag(db, users, for_self=False)
    allowed = set(scoped_subjects(user))
    if len(allowed) != len(SUBJECTS):
        data["items"] = [row for row in data["items"] if row["subject"] in allowed]
        data["subjects"] = [c for c in data["subjects"] if c["id"] in allowed]
    return data


@router.post("/students")
def add_student(body: StudentIn, _user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    exists = db.scalar(select(User).where(User.username == body.username.strip()))
    if exists:
        raise HTTPException(409, "这个名字已经有人用了")
    student = User(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        role="student",
        grade=body.grade,
        display_name=(body.display_name or body.username).strip(),
    )
    db.add(student)
    db.commit()
    return {"ok": True, "id": student.id}


@router.get("/students")
def list_students(_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(User).where(User.role == "student").order_by(User.id)).all()
    return {
        "students": [
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name or u.username,
                "grade": u.grade,
                "grade_name": grade_label(u.grade),
            }
            for u in rows
        ]
    }


@router.get("/students/{student_id}/work")
def student_work(student_id: int, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404, "找不到这个学生")
    runs = db.scalars(
        select(ChallengeRun).where(ChallengeRun.user_id == student.id).order_by(ChallengeRun.id.desc())
    ).all()
    attempts = db.scalars(
        select(PaperAttempt).where(PaperAttempt.user_id == student.id).order_by(PaperAttempt.id.desc())
    ).all()
    challenges = []
    for run in runs:
        if not sees_subject(user, run.subject):
            continue
        slugs = json.loads(run.slugs_json)
        challenges.append(
            {
                "id": run.id,
                "kind": "challenge",
                "title": f"闯关 · {SUBJECTS.get(run.subject, run.subject)}",
                "status": "进行中" if run.status == "active" else "已完成",
                "total": len(slugs),
                **score_context(db, student.id, "challenge", run.id, slugs),
            }
        )
    papers = []
    for attempt in attempts:
        paper = attempt.paper
        if not sees_subject(user, paper.subject):
            continue
        slugs = json.loads(paper.slugs_json)
        papers.append(
            {
                "id": attempt.id,
                "kind": "paper",
                "paper_id": paper.id,
                "title": paper.title,
                "status": "已交卷" if attempt.status == "submitted" else "未交卷",
                "total": len(slugs),
                **score_context(db, student.id, "paper", attempt.id, slugs),
            }
        )
    return {
        "student": {
            "id": student.id,
            "username": student.username,
            "display_name": student.display_name or student.username,
            "grade_name": grade_label(student.grade),
        },
        "challenges": challenges,
        "papers": papers,
    }


@router.get("/review/challenge/{run_id}")
def review_run(run_id: int, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    run = db.get(ChallengeRun, run_id)
    if not run:
        raise HTTPException(404, "找不到这次闯关")
    _need_subject(user, run.subject)
    data = review_challenge(db, run_id)
    if not data:
        raise HTTPException(404, "找不到这次闯关")
    return data


@router.get("/review/paper/{attempt_id}")
def review_attempt(attempt_id: int, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    attempt = db.get(PaperAttempt, attempt_id)
    if not attempt:
        raise HTTPException(404, "找不到这份试卷")
    _need_subject(user, attempt.paper.subject)
    data = review_paper(db, attempt_id)
    if not data:
        raise HTTPException(404, "找不到这份试卷")
    return data


@router.post("/assemble")
def assemble(body: AssembleIn, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    if body.subject not in SUBJECTS:
        raise HTTPException(400, "没有这个科目")
    _need_subject(user, body.subject)
    wanted = [row for row in body.sections if int(row.count or 0) > 0]
    chosen: list = []
    section_rows: list[dict] = []
    used: set[str] = set()
    if wanted:
        for row in wanted:
            spec = section_spec(row.id)
            if not spec:
                raise HTTPException(400, "没有这类题")
            types = list(spec["types"])
            pool = [
                item
                for item in bank.list(
                    subject=body.subject,
                    grade=body.grade,
                    difficulty=body.difficulty,
                    types=types,
                    tags=body.tags or None,
                )
                if item.slug not in used
            ]
            if len(pool) < row.count:
                raise HTTPException(400, f"{spec['name']}在题库里只有 {len(pool)} 道，不够 {row.count} 道")
            random.shuffle(pool)
            pick = pool[: row.count]
            for item in pick:
                used.add(item.slug)
            chosen.extend(pick)
            heading = fill_heading(row.heading or str(spec["heading"]), pick, len(section_rows), str(spec["name"]))
            section_rows.append({"id": row.id, "heading": heading, "slugs": [i.slug for i in pick]})
    else:
        pool = bank.list(
            subject=body.subject,
            grade=body.grade,
            difficulty=body.difficulty,
            types=body.types or None,
            tags=body.tags or None,
        )
        if not pool:
            pool = bank.list(subject=body.subject, grade=body.grade, tags=body.tags or None)
        if not pool:
            pool = bank.list(subject=body.subject, tags=body.tags or None)
        if not pool:
            raise HTTPException(400, "题库里还没有合适的题")
        n = int(body.count or 0)
        if n <= 0:
            raise HTTPException(400, "请至少选一类题，并写上数量")
        random.shuffle(pool)
        chosen = pool[:n]
        section_rows = [{"id": "all", "heading": "", "slugs": [i.slug for i in chosen]}]
    kind = body.kind if body.kind in {"homework", "quiz", "exam"} else "homework"
    duration = int(body.duration_minutes or 0)
    if duration:
        kind = "exam"
    title = f"{SUBJECTS[body.subject]}练习"
    paper = Paper(
        title=title,
        subject=body.subject,
        grade=body.grade,
        kind=kind,
        slugs_json=json.dumps([i.slug for i in chosen], ensure_ascii=False),
        sections_json=json.dumps(section_rows, ensure_ascii=False),
        allow_revise=kind != "exam" and duration <= 0,
        duration_minutes=duration,
        created_by=user.id,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return {
        "id": paper.id,
        "title": paper.title,
        "kind": paper.kind,
        "count": len(chosen),
        "duration_minutes": duration,
        "items": [i.summary() for i in chosen],
        "sections": section_rows,
    }


@router.get("/papers")
def list_papers(user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    papers = db.scalars(select(Paper).order_by(Paper.id.desc())).all()
    out = []
    for paper in papers:
        if not sees_subject(user, paper.subject):
            continue
        ranking = paper_ranking(db, paper)
        pending = sum(int(r["pending"]) for r in ranking)
        out.append(
            {
                "id": paper.id,
                "title": paper.title,
                "subject": paper.subject,
                "subject_name": SUBJECTS.get(paper.subject, paper.subject),
                "kind": paper.kind,
                "count": len(json.loads(paper.slugs_json)),
                "joined": len(paper.attempts),
                "submitted": sum(1 for r in ranking if r["submitted"]),
                "pending": pending,
                **timing_fields(paper),
            }
        )
    return {"papers": out}


@router.get("/papers/{paper_id}")
def paper_detail(paper_id: int, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "找不到这份试卷")
    _need_subject(user, paper.subject)
    ranking = paper_ranking(db, paper)
    return {
        "id": paper.id,
        "title": paper.title,
        "subject": paper.subject,
        "subject_name": SUBJECTS.get(paper.subject, paper.subject),
        "kind": paper.kind,
        "count": len(json.loads(paper.slugs_json)),
        "ranking": ranking,
        "students": ranking,
        **timing_fields(paper),
    }


@router.get("/items")
def list_bank_items(
    subject: str | None = None,
    grade: int | None = Query(None),
    difficulty: str | None = None,
    item_type: str | None = Query(None, alias="type"),
    tags: list[str] = Query(default=[]),
    user: User = Depends(get_admin_user),
) -> dict:
    allowed = set(scoped_subjects(user))
    rows = [i for i in bank.items.values() if i.subject in allowed]
    if subject:
        _need_subject(user, subject)
        rows = [i for i in rows if i.subject == subject]
    if grade:
        rows = [i for i in rows if i.grade == grade]
    if difficulty:
        rows = [i for i in rows if i.difficulty == difficulty]
    if item_type:
        rows = [i for i in rows if i.type == item_type]
    topics = sorted({t for i in rows for t in i.tags})
    need = [t for t in tags if t]
    if need:
        rows = [i for i in rows if all(t in i.tags for t in need)]
    rows.sort(key=lambda i: (i.subject, i.grade, i.title, i.slug))
    return {"items": [i.summary() for i in rows], "topics": topics, "count": len(rows)}


@router.get("/items/{slug}")
def get_bank_item(slug: str, user: User = Depends(get_admin_user)) -> dict:
    try:
        item = bank.get(slug)
    except BankError:
        raise HTTPException(404, "找不到这道题")
    _need_subject(user, item.subject)
    return item.editor()


@router.put("/items/{slug}")
def save_bank_item(slug: str, body: ItemEditIn, user: User = Depends(get_admin_user)) -> dict:
    try:
        existing = bank.get(slug)
    except BankError:
        raise HTTPException(404, "找不到这道题")
    _need_subject(user, existing.subject)
    subject = body.subject or existing.subject
    _need_subject(user, subject)
    try:
        item = item_from_editor(slug, subject, existing.type, body.model_dump())
    except BankError as exc:
        raise HTTPException(400, str(exc) or "题目不完整") from exc
    save_item(item)
    bank.reload()
    try:
        saved = bank.get(slug)
    except BankError:
        raise HTTPException(500, "保存了但没读回来")
    return saved.editor()


@router.get("/skill")
def skill(_user: User = Depends(get_admin_user)) -> dict:
    text = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.is_file() else ""
    return {"text": text}


@router.post("/ingest/paste")
def ingest_paste(body: PasteIn, user: User = Depends(get_admin_user)) -> dict:
    items = [i for i in items_from_text(body.text) if sees_subject(user, i.subject)]
    if not items:
        raise HTTPException(400, "没认出题目，再试一次")
    for item in items:
        save_item(item)
    bank.reload()
    return {"ok": True, "count": len(items), "titles": [i.title for i in items]}


@router.post("/ingest/file")
async def ingest_file(file: UploadFile = File(...), user: User = Depends(get_admin_user)) -> dict:
    data = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".zip"):
        items = items_from_zip(data)
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "没认出题目，再试一次") from exc
        items = items_from_text(text)
    items = [i for i in items if sees_subject(user, i.subject)]
    if not items:
        raise HTTPException(400, "没认出题目，再试一次")
    for item in items:
        save_item(item)
    bank.reload()
    return {"ok": True, "count": len(items), "titles": [i.title for i in items]}


@router.post("/items/plain")
def add_plain(body: PlainItemIn, user: User = Depends(get_admin_user)) -> dict:
    _need_subject(user, body.subject)
    item = plain_item(body.subject, body.type, body.stem, body.answer, body.grade, body.difficulty, body.title)
    save_item(item)
    bank.reload()
    return {"ok": True, "title": item.title}


@router.post("/bank/update")
def update_bank(_user: User = Depends(get_admin_user)) -> dict:
    script = ROOT / "scripts" / "update-from-github.sh"
    if script.exists() and (ROOT / ".git").exists():
        try:
            subprocess.run(["bash", str(script)], cwd=str(ROOT), check=False, timeout=120)
        except Exception:
            bank.reload()
            return {"ok": True, "message": "已经重新读了本机题目。要从网上更新，请到主机上点更新。"}
    bank.reload()
    return {"ok": True, "message": f"题库已更新，现在有 {len(bank.items)} 道题。", "count": len(bank.items)}


@router.get("/answers/{answer_id}")
def get_answer(answer_id: int, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    row = db.get(ItemAnswer, answer_id)
    if not row:
        raise HTTPException(404, "找不到这份作答")
    item = bank.get(row.item_slug)
    _need_subject(user, item.subject)
    part = next(p for p in item.parts if p.id == row.part_id)
    student = db.get(User, row.user_id)
    return {
        "id": row.id,
        "student": student.display_name if student else "",
        "title": item.title,
        "stem": part.stem,
        "left_md": item.left_md,
        "value": load_value(row.value_json),
        "photos": json.loads(row.photos_json or "[]"),
        "status": row.status,
        "score": row.override_score if row.status == "overridden" else row.score,
        "max_score": row.max_score,
        "comment": row.override_comment or row.llm_comment,
        "rubric": part.rubric,
        "reference": part.reference,
    }


@router.get("/queue")
def queue(user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(ItemAnswer)
        .where(ItemAnswer.status.in_(["pending", "graded", "overridden"]))
        .order_by(ItemAnswer.id.desc())
    ).all()
    out = []
    for row in rows:
        item = bank.items.get(row.item_slug)
        part = next((p for p in item.parts if p.id == row.part_id), None) if item else None
        if part and part.type in OBJECTIVE_TYPES:
            continue
        if item and not sees_subject(user, item.subject):
            continue
        student = db.get(User, row.user_id)
        out.append(
            {
                "id": row.id,
                "student": (student.display_name or student.username) if student else "",
                "student_id": row.user_id,
                "title": item.title if item else row.item_slug,
                "status": row.status,
                "status_label": {"pending": "待评分", "graded": "已评分", "overridden": "已改判"}.get(row.status, row.status),
                "score": row.override_score if row.status == "overridden" else row.score,
                "max_score": row.max_score,
                "kind": row.context_type,
                "context_id": row.context_id,
            }
        )
    return {"answers": out}


@router.post("/grade")
def grade(body: GradeIn, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    row = db.get(ItemAnswer, body.answer_id)
    if not row:
        raise HTTPException(404, "找不到这份作答")
    item = bank.get(row.item_slug)
    _need_subject(user, item.subject)
    if body.regrade:
        part = next(p for p in item.parts if p.id == row.part_id)
        photos = json.loads(row.photos_json or "[]")
        result = grade_part_llm(item, part, str(load_value(row.value_json) or ""), photos)
        if result:
            row.score = float(result["total"])
            row.llm_json = json.dumps(result, ensure_ascii=False)
            row.llm_comment = result.get("comment")
            row.status = "graded"
        else:
            enqueue(row.id, row.item_slug, row.part_id, photos)
            row.status = "pending"
        db.commit()
        return {"ok": True, "status": row.status, "score": row.score}
    row.override_score = float(body.score)
    row.override_comment = body.comment
    row.override_by = user.id
    row.status = "overridden"
    db.commit()
    return {"ok": True, "score": row.override_score}


@router.post("/grade/retry-pending")
def retry_pending(user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(ItemAnswer).where(ItemAnswer.status == "pending")).all()
    n = 0
    for row in rows:
        item = bank.items.get(row.item_slug)
        if not item or not sees_subject(user, item.subject):
            continue
        photos = json.loads(row.photos_json or "[]")
        enqueue(row.id, row.item_slug, row.part_id, photos)
        n += 1
    return {"ok": True, "count": n}


def _llm_payload(cfg: dict, models: list[str] | None = None, reach_error: str = "") -> dict:
    return {
        "base_url": cfg["base_url"] or DEFAULT_LLM_BASE_URL,
        "model": cfg["model"],
        "chat_path": cfg["chat_path"] or "/chat/completions",
        "has_key": bool(cfg["api_key"]),
        "configured": llm_configured(),
        "from_env": llm_from_env(),
        "enable_thinking": cfg.get("enable_thinking") == "1",
        "reasoning_effort": cfg.get("reasoning_effort") or ("none" if cfg.get("enable_thinking") != "1" else ""),
        "models": models or [],
        "reach_error": reach_error,
    }


@router.get("/llm")
def get_llm(user: User = Depends(get_admin_user)) -> dict:
    cfg = llm_settings()
    base = cfg["base_url"] or DEFAULT_LLM_BASE_URL
    models: list[str] = []
    err = ""
    try:
        models = list_remote_models(base, cfg["api_key"])
    except Exception:
        err = "连不上本机模型服务。确认 127.0.0.1:8080 已开着。"
    model = cfg["model"] or (models[0] if models else "")
    shown = dict(cfg)
    shown["base_url"] = base
    shown["model"] = model
    return _llm_payload(shown, models, err)


@router.put("/llm")
@router.post("/llm")
def put_llm(body: LlmSettingsIn, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    if llm_from_env():
        raise HTTPException(400, "正在用的地址是启动时定的，网页保存改不了。让装机的人改启动配置。")
    current = llm_settings()
    key = body.api_key
    if body.keep_key and not key:
        key = current["api_key"]
    base = (body.base_url or DEFAULT_LLM_BASE_URL).strip() or DEFAULT_LLM_BASE_URL
    model = (body.model or "").strip()
    if not model:
        try:
            found = list_remote_models(base, key)
        except Exception:
            found = []
        if found:
            model = found[0]
    if not model:
        raise HTTPException(400, "请选一个模型，或先点读取列表")
    save_llm_file(
        base,
        model,
        key,
        body.chat_path or "/chat/completions",
        body.enable_thinking,
        body.reasoning_effort,
    )
    start_worker()
    pending = db.scalars(select(ItemAnswer).where(ItemAnswer.status == "pending")).all()
    n = 0
    for row in pending:
        item = bank.items.get(row.item_slug)
        if not item or not sees_subject(user, item.subject):
            continue
        photos = json.loads(row.photos_json or "[]")
        enqueue(row.id, row.item_slug, row.part_id, photos)
        n += 1
    out = get_llm(user)
    out["queued"] = n
    return out


@router.post("/llm/test")
def test_llm(body: LlmSettingsIn, user: User = Depends(get_admin_user)) -> dict:
    current = llm_settings()
    key = body.api_key
    if body.keep_key and not key:
        key = current["api_key"]
    base = (body.base_url or current["base_url"] or DEFAULT_LLM_BASE_URL).strip()
    model = (body.model or current["model"]).strip()
    path = body.chat_path or current["chat_path"] or "/chat/completions"
    if not model:
        raise HTTPException(400, "请先选模型")
    try:
        reply = ping_llm(base, model, key, path, body.enable_thinking, body.reasoning_effort)
    except Exception as exc:
        raise HTTPException(400, f"没连上：{exc}") from exc
    return {"ok": True, "reply": reply[:80]}
