from __future__ import annotations

import json
import random
import re
import subprocess
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DEFAULT_LLM_BASE_URL, ROOT, SKILL_PATH, llm_configured, llm_from_env, llm_settings, save_llm_file
from ..constants import DIFFICULTIES, GRADE_LABELS, OBJECTIVE_TYPES, PAPER_SECTIONS, SUBJECTS, TYPES, grade_label
from ..db import get_db
from ..deps import get_admin_user, hash_password
from ..models import ChallengeRun, ItemAnswer, Paper, PaperAttempt, PaperAudience, StudentGroup, User
from ..schemas import GenerateItemsIn, GeneratedItemSaveIn, AssembleIn, GradeIn, GroupIn, ItemEditIn, LlmSettingsIn, MemberIn, PaperWindowIn, PasteIn, PlainItemIn, StudentIn, StudentPatchIn
from ..services.access import sees_subject, scoped_subjects
from ..services.answers import (
    effective_comment,
    effective_score,
    grade_paper_attempts,
    paper_can_release_scores,
    paper_ungraded_count,
    score_context,
    scores_visible_for_paper,
    settle_closed_groups,
    submit_item,
)
from ..services.bank import BankError, bank
from ..services.curriculum import CurriculumError
from ..services.generation import GenerationError, generate, validate
from ..services.ingest import item_from_editor, items_from_text, items_from_zip, plain_item, save_item
from ..services.paper_layout import fill_heading, section_spec
from ..services.llm import enqueue, list_remote_models, ping_llm, start_worker
from ..services.grade import load_value
from ..services.review import review_challenge, review_paper
from ..services.scores import scores_by_tag
from ..services.groups import (
    add_membership,
    audience_payload,
    group_row,
    group_students,
    list_groups,
    require_group,
    remove_membership,
    roster_for_paper,
    set_memberships,
    student_public,
    teacher_label,
    ungrouped_count,
)
from ..services.timing import (
    paper_can_start_grade,
    paper_expired,
    paper_ranking,
    paper_scripts,
    paper_window,
    timing_fields,
    utc_naive,
)

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
            visible = scores_visible_for_paper(paper)
            ctx = score_context(db, student.id, "paper", attempt.id, slugs) if visible else {"score": 0, "max_score": 0, "pending": 0}
            if visible:
                score += float(ctx["score"])
                maximum += float(ctx["max_score"])
                pending += int(ctx["pending"])
            paper_rows.append(
                {
                    "id": attempt.id,
                    "paper_id": paper.id,
                    "title": paper.title,
                    "status": attempt.status,
                    "scores_released": visible,
                    **ctx,
                }
            )
        out.append(
            {
                "id": student.id,
                "username": student.username,
                "display_name": teacher_label(student),
                "grade": student.grade,
                "grade_name": grade_label(student.grade),
                "group_label": student_public(student)["group_label"],
                "class_label": student_public(student)["class_label"],
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


@router.get("/groups")
def get_groups(_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    return {"groups": list_groups(db), "ungrouped": ungrouped_count(db)}


@router.post("/groups")
def add_group(body: GroupIn, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "请写分组名字")
    kind = body.kind if body.kind in {"class", "group"} else "group"
    parent = None
    grade = body.grade
    if kind == "class":
        if not grade:
            raise HTTPException(400, "班级要选年级")
        exists = db.scalar(
            select(StudentGroup).where(
                StudentGroup.kind == "class", StudentGroup.grade == grade, StudentGroup.name == name
            )
        )
        if exists:
            raise HTTPException(409, "这个年级已经有这个班了")
        parent_id = None
    else:
        parent_id = body.parent_id
        if parent_id:
            parent = require_group(db, parent_id)
            if parent.kind != "class":
                raise HTTPException(400, "班内分组请挂在班级下面")
            grade = parent.grade
            exists = db.scalar(
                select(StudentGroup).where(StudentGroup.parent_id == parent.id, StudentGroup.name == name)
            )
            if exists:
                raise HTTPException(409, "这个班里已经有这个分组了")
        else:
            exists = db.scalar(
                select(StudentGroup).where(
                    StudentGroup.kind == "group",
                    StudentGroup.parent_id.is_(None),
                    StudentGroup.name == name,
                )
            )
            if exists:
                raise HTTPException(409, "已经有这个分组了")
    group = StudentGroup(name=name, kind=kind, grade=grade, parent_id=parent_id, created_by=user.id)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group_row(db, group)


@router.get("/groups/ungrouped")
def get_ungrouped(_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    students = [student_public(u) for u in group_students(db, None)]
    return {
        "group": {
            "id": 0,
            "name": "未分组",
            "label": "未分组",
            "grade": None,
            "grade_name": "",
            "count": len(students),
        },
        "students": students,
        "ungrouped": True,
    }


@router.get("/groups/{group_id}")
def get_group(group_id: int, _user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    group = db.get(StudentGroup, group_id)
    if not group:
        raise HTTPException(404, "找不到这个分组")
    students = [student_public(u) for u in group_students(db, group.id)]
    row = group_row(db, group)
    row["count"] = len(students)
    return {"group": row, "students": students, "ungrouped": False}


@router.post("/groups/{group_id}/members")
def add_group_member(
    group_id: int, body: MemberIn, _user: User = Depends(get_admin_user), db: Session = Depends(get_db)
) -> dict:
    group = require_group(db, group_id)
    student = db.get(User, body.student_id)
    if not student or student.role != "student":
        raise HTTPException(404, "找不到这个学生")
    add_membership(db, student, group)
    db.commit()
    return get_group(group_id, _user, db)


@router.delete("/groups/{group_id}/members/{student_id}")
def remove_group_member(
    group_id: int, student_id: int, _user: User = Depends(get_admin_user), db: Session = Depends(get_db)
) -> dict:
    require_group(db, group_id)
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404, "找不到这个学生")
    group = require_group(db, group_id)
    remove_membership(db, student, group)
    db.commit()
    return get_group(group_id, _user, db)


@router.post("/students")
def add_student(body: StudentIn, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    exists = db.scalar(select(User).where(User.username == body.username.strip()))
    if exists:
        raise HTTPException(409, "这个名字已经有人用了")
    student = User(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        role="student",
        grade=body.grade,
        display_name=(body.display_name or body.username).strip(),
        created_by=user.id,
    )
    db.add(student)
    db.flush()
    set_memberships(db, student, body.group_ids or [], body.grade)
    db.commit()
    db.refresh(student)
    return {"ok": True, "id": student.id, "student": student_public(student)}


@router.put("/students/{student_id}")
def update_student(
    student_id: int, body: StudentPatchIn, _user: User = Depends(get_admin_user), db: Session = Depends(get_db)
) -> dict:
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(404, "找不到这个学生")
    student.display_name = (body.display_name or "").strip() or student.username
    set_memberships(db, student, body.group_ids, body.grade)
    db.commit()
    db.refresh(student)
    return student_public(student)


@router.get("/students")
def list_students(_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(User).where(User.role == "student").order_by(User.id)).all()
    return {"students": [student_public(u) for u in rows]}


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
        visible = scores_visible_for_paper(paper)
        row = {
            "id": attempt.id,
            "kind": "paper",
            "paper_id": paper.id,
            "title": paper.title,
            "scores_released": visible,
            "status": "缺考" if attempt.status == "absent" else "已交卷" if attempt.status == "submitted" else "未交卷",
            "total": len(slugs),
        }
        if visible:
            row.update(score_context(db, student.id, "paper", attempt.id, slugs))
        else:
            row.update({"score": None, "max_score": None, "pending": 0})
        papers.append(row)
    return {
        "student": student_public(student),
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
    data = review_paper(db, attempt_id, named=False)
    if not data:
        raise HTTPException(404, "找不到这份试卷")
    return data


@router.get("/students/{student_id}/work/paper/{attempt_id}")
def student_paper_review(
    student_id: int, attempt_id: int, user: User = Depends(get_admin_user), db: Session = Depends(get_db)
) -> dict:
    student = db.get(User, student_id)
    attempt = db.get(PaperAttempt, attempt_id)
    if not student or student.role != "student" or not attempt or attempt.user_id != student.id:
        raise HTTPException(404, "找不到这次作答")
    _need_subject(user, attempt.paper.subject)
    if not scores_visible_for_paper(attempt.paper):
        raise HTTPException(403, "成绩还没发布，不能从学生页看这次作答。改判请去测验。")
    data = review_paper(db, attempt_id, named=True)
    if not data:
        raise HTTPException(404, "找不到这次作答")
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
        "released": False,
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
        ungraded = paper_ungraded_count(db, paper)
        roster = roster_for_paper(db, paper)
        joined = len(roster) if paper.audiences else len(paper.attempts)
        out.append(
            {
                "id": paper.id,
                "title": paper.title,
                "subject": paper.subject,
                "subject_name": SUBJECTS.get(paper.subject, paper.subject),
                "kind": paper.kind,
                "count": len(json.loads(paper.slugs_json)),
                "joined": joined,
                "submitted": sum(1 for r in ranking if r["submitted"]),
                "pending": pending,
                "ungraded": ungraded,
                "can_release_scores": paper_can_release_scores(db, paper),
                "scripts": len(paper.attempts),
                "audiences": audience_payload(paper),
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
    scripts = paper_scripts(db, paper)
    ranking = [row for row in scripts if row["complete"]]
    ungraded = paper_ungraded_count(db, paper)
    roster = roster_for_paper(db, paper)
    return {
        "id": paper.id,
        "title": paper.title,
        "subject": paper.subject,
        "subject_name": SUBJECTS.get(paper.subject, paper.subject),
        "kind": paper.kind,
        "count": len(json.loads(paper.slugs_json)),
        "scripts": scripts,
        "ranking": ranking,
        "ungraded": ungraded,
        "can_release_scores": paper_can_release_scores(db, paper),
        "audiences": audience_payload(paper),
        "joined": len(roster) if paper.audiences else len(paper.attempts),
        **timing_fields(paper),
    }


def _apply_window(paper: Paper, body: PaperWindowIn) -> None:
    opens = utc_naive(body.opens_at)
    closes = utc_naive(body.closes_at)
    if closes <= opens:
        raise HTTPException(400, "结束时间必须晚于开始时间")
    paper.opens_at = opens
    paper.closes_at = closes
    paper.duration_minutes = max(1, int((closes - opens).total_seconds() // 60))


def _apply_audiences(db: Session, paper: Paper, body: PaperWindowIn) -> None:
    specs = body.audiences or []
    if not specs:
        raise HTTPException(400, "请至少选一个分组作为测验对象。")
    seen: set[int] = set()
    wanted: list[tuple[int, datetime | None, datetime | None]] = []
    for spec in specs:
        if spec.group_id in seen:
            continue
        seen.add(spec.group_id)
        require_group(db, spec.group_id)
        opens = utc_naive(spec.opens_at) if spec.opens_at else None
        closes = utc_naive(spec.closes_at) if spec.closes_at else None
        if (opens is None) != (closes is None):
            raise HTTPException(400, "分组单独时间要同时写开始和结束")
        if opens and closes and closes <= opens:
            raise HTTPException(400, "分组结束时间必须晚于开始时间")
        wanted.append((spec.group_id, opens, closes))
    existing = {row.group_id: row for row in list(paper.audiences or [])}
    keep = {gid for gid, _, _ in wanted}
    for gid, opens, closes in wanted:
        row = existing.get(gid)
        if row:
            row.opens_at = opens
            row.closes_at = closes
        else:
            db.add(PaperAudience(paper_id=paper.id, group_id=gid, opens_at=opens, closes_at=closes))
    for gid, row in existing.items():
        if gid not in keep:
            db.delete(row)


@router.post("/papers/{paper_id}/release")
def release_paper(
    paper_id: int,
    body: PaperWindowIn,
    user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "找不到这份试卷")
    _need_subject(user, paper.subject)
    if paper.released_at:
        raise HTTPException(400, "已经发布了")
    _apply_window(paper, body)
    _apply_audiences(db, paper, body)
    paper.released_at = datetime.utcnow()
    db.commit()
    return paper_detail(paper_id, user, db)


@router.post("/papers/{paper_id}/window")
def set_paper_window(
    paper_id: int,
    body: PaperWindowIn,
    user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "找不到这份试卷")
    _need_subject(user, paper.subject)
    if not paper.released_at:
        raise HTTPException(400, "请先发布试卷")
    if paper.grading_started_at:
        raise HTTPException(400, "已经开始评分，不能再改时间")
    if paper_window(paper) == "closed":
        raise HTTPException(400, "答题已经截止")
    if paper_window(paper) == "open" and utc_naive(body.opens_at) > datetime.utcnow():
        raise HTTPException(400, "已经开考，不能把开始时间改到以后")
    _apply_window(paper, body)
    _apply_audiences(db, paper, body)
    db.commit()
    return paper_detail(paper_id, user, db)


@router.post("/papers/{paper_id}/start-grade")
def start_grade(paper_id: int, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "找不到这份试卷")
    _need_subject(user, paper.subject)
    if not paper_can_start_grade(paper):
        raise HTTPException(400, "答题还没截止，不能开始评分")
    settle_closed_groups(db, paper)
    if not paper.grading_started_at:
        paper.grading_started_at = datetime.utcnow()
    n = grade_paper_attempts(db, paper)
    db.commit()
    out = paper_detail(paper_id, user, db)
    out["graded_items"] = n
    return out


@router.post("/papers/{paper_id}/release-scores")
def release_scores(paper_id: int, user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(404, "找不到这份试卷")
    _need_subject(user, paper.subject)
    if not paper.grading_started_at:
        raise HTTPException(400, "请先开始评分")
    ungraded = paper_ungraded_count(db, paper)
    if ungraded:
        raise HTTPException(400, f"还有 {ungraded} 问没出分（含模型排队），出齐才能发布成绩")
    paper.scores_released_at = datetime.utcnow()
    db.commit()
    return paper_detail(paper_id, user, db)


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


@router.post("/items/generate")
def generate_items(body: GenerateItemsIn, user: User = Depends(get_admin_user)) -> dict:
    if body.subject not in SUBJECTS or body.difficulty not in DIFFICULTIES or body.type not in TYPES or not body.topic.strip():
        raise HTTPException(400, "出题参数不正确，请检查科目、难度、题型和知识点")
    _need_subject(user, body.subject)
    try:
        return generate(body.model_dump())
    except (GenerationError, CurriculumError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/items/generated/save")
def save_generated_item(body: GeneratedItemSaveIn, user: User = Depends(get_admin_user)) -> dict:
    if body.subject not in SUBJECTS or body.difficulty not in DIFFICULTIES or body.type not in TYPES:
        raise HTTPException(400, "题目参数不正确")
    _need_subject(user, body.subject)
    if not re.fullmatch(r"generated-[0-9a-f]{32}", body.slug):
        raise HTTPException(400, "题目编号无效，请重新生成")
    if body.slug in bank.items:
        raise HTTPException(409, "题目编号已存在，请重新生成")
    payload = body.model_dump()
    try:
        # Apply the same strict structural checks after editing, then preserve the issued slug.
        validate({"items": [payload]}, {**payload, "count": 1})
        item = item_from_editor(body.slug, body.subject, body.type, payload)
        save_item(item, exclusive=True)
    except FileExistsError:
        raise HTTPException(409, "题目编号已存在，请重新生成") from None
    except (GenerationError, BankError, ValueError, TypeError):
        raise HTTPException(400, "题目内容无效，请检查题干、答案和分值") from None
    bank.reload()
    return bank.get(body.slug).editor()


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
    item = plain_item(
        body.subject,
        body.type,
        body.stem,
        body.answer,
        body.grade,
        body.difficulty,
        body.title,
        body.tags,
    )
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
        "student": teacher_label(student),
        "title": item.title,
        "stem": part.stem,
        "left_md": item.left_md,
        "value": load_value(row.value_json),
        "photos": json.loads(row.photos_json or "[]"),
        "status": row.status,
        "score": effective_score(row),
        "llm_score": row.score,
        "admin_score": row.override_score,
        "max_score": row.max_score,
        "comment": effective_comment(row),
        "llm_comment": row.llm_comment,
        "admin_comment": row.override_comment,
        "admin_touched": row.override_score is not None,
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
        if row.context_type == "paper":
            attempt = db.get(PaperAttempt, row.context_id)
            if not scores_visible_for_paper(attempt.paper if attempt else None):
                continue
        student = db.get(User, row.user_id)
        out.append(
            {
                "id": row.id,
                "student": teacher_label(student),
                "student_id": row.user_id,
                "title": item.title if item else row.item_slug,
                "status": row.status,
                "status_label": {"pending": "待评分", "graded": "已评分", "overridden": "已改判"}.get(row.status, row.status),
                "score": effective_score(row),
                "llm_score": row.score,
                "admin_score": row.override_score,
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
        photos = json.loads(row.photos_json or "[]")
        row.score = None
        row.llm_json = None
        row.llm_comment = None
        if row.override_score is None:
            row.status = "pending"
            row.graded_at = None
        db.commit()
        enqueue(row.id, row.item_slug, row.part_id, photos)
        return {
            "ok": True,
            "status": row.status,
            "score": effective_score(row),
            "llm_score": None,
            "admin_score": row.override_score,
            "comment": effective_comment(row),
            "llm_comment": None,
        }
    row.override_score = float(body.score)
    row.override_comment = body.comment
    row.override_by = user.id
    row.status = "overridden"
    db.commit()
    return {
        "ok": True,
        "score": row.override_score,
        "llm_score": row.score,
        "admin_score": row.override_score,
        "comment": row.override_comment,
    }


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
