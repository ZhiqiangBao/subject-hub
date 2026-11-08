from __future__ import annotations

import json
import re
import uuid
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import UPLOAD_DIR, ensure_dirs
from ..db import get_db, reserve_write
from ..deps import get_current_user, is_admin_role
from ..models import ChallengeRun, ItemAnswer, PaperAttempt, User
from ..services.access import sees_subject
from ..services.answers import get_or_create_answer
from ..services.bank import bank
from ..services.snapshots import paper_item
from ..services.timing import audience_for_user, paper_visible_to, paper_window

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
MAX_BYTES = 6 * 1024 * 1024
PHOTO_NAME = re.compile(r"([1-9]\d{0,17})-[a-f0-9]{32}\.(?:jpg|jpeg|png|webp)")


def _format(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    raise HTTPException(400, "请上传 JPEG、PNG 或 WebP 照片")


def _writable_part(db: Session, user: User, kind: str, ident: int, slug: str, part_id: str):
    if kind == "paper":
        attempt = db.get(PaperAttempt, ident)
        if not attempt or attempt.user_id != user.id or not paper_visible_to(attempt.paper, user):
            raise HTTPException(404, "找不到这份答卷")
        paper = attempt.paper
        if (paper.grading_started_at or paper.scores_released_at or attempt.status == "absent"
                or (attempt.status == "submitted" and not paper.allow_revise)
                or paper_window(paper, audience=audience_for_user(paper, user)) != "open"):
            raise HTTPException(409, "现在不能再修改这份答卷")
        item = paper_item(paper, slug)
    elif kind == "challenge":
        run = db.get(ChallengeRun, ident)
        if not run or run.user_id != user.id:
            raise HTTPException(404, "找不到这次闯关")
        slugs = json.loads(run.slugs_json)
        if run.status != "active" or slugs[run.current_index:run.current_index + 1] != [slug]:
            raise HTTPException(409, "只能给正在作答的这一题加照片")
        item = bank.items.get(slug)
    else:
        raise HTTPException(400, "不能上传到这里")
    part = next((p for p in item.parts if p.id == part_id), None) if item else None
    if not part or not part.allow_photo or part.type not in {"short", "essay"}:
        raise HTTPException(400, "这问不接收照片")
    row = get_or_create_answer(db, user.id, kind, ident, item, part_id)
    if row.status not in ({"draft", "submitted"} if kind == "paper" else {"draft"}):
        raise HTTPException(409, "这问已经锁定")
    return row


@router.post("/{context_type}/{context_id}/{slug}/{part_id}")
async def upload_photo(context_type: str, context_id: int, slug: str, part_id: str,
                       file: UploadFile = File(...), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> dict:
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "照片超过 6 MB")
    suffix = _format(data)
    # Recheck after reading the upload. Serialize the check and update with
    # submissions and concurrent photos on the project's SQLite database.
    reserve_write(db)
    row = _writable_part(db, user, context_type, context_id, slug, part_id)
    photos = json.loads(row.photos_json or "[]")
    ensure_dirs()
    name = f"{user.id}-{uuid.uuid4().hex}{suffix}"
    dest = UPLOAD_DIR / name
    output = dest.open("xb")
    try:
        with output:
            output.write(data)
        row.photos_json = json.dumps((photos + [name])[-3:])
        db.commit()
    except Exception:
        db.rollback()
        dest.unlink(missing_ok=True)
        raise
    for old_name in photos[:-2]:
        if PHOTO_NAME.fullmatch(old_name) and old_name.startswith(f"{user.id}-"):
            try:
                (UPLOAD_DIR / old_name).unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("无法清理已替换的答题照片")
    return {"ok": True, "photos": (photos + [name])[-3:]}


@router.get("/file/{name}")
def get_file(name: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    missing = HTTPException(404, "找不到这张照片")
    match = PHOTO_NAME.fullmatch(name)
    if not match:
        raise missing
    owner_id = int(match[1])
    if user.id != owner_id and not is_admin_role(user):
        raise missing
    rows = db.scalars(select(ItemAnswer).where(
        ItemAnswer.user_id == owner_id, ItemAnswer.photos_json.contains(f'"{name}"'))).all()
    for row in rows:
        if row.context_type == "paper":
            attempt = db.get(PaperAttempt, row.context_id)
            if not attempt or attempt.user_id != owner_id or row.item_slug not in json.loads(attempt.paper.slugs_json):
                continue
            if user.id == owner_id and not paper_visible_to(attempt.paper, user):
                continue
            subject = attempt.paper.subject
        elif row.context_type == "challenge":
            run = db.get(ChallengeRun, row.context_id)
            if not run or run.user_id != owner_id or row.item_slug not in json.loads(run.slugs_json):
                continue
            item = bank.items.get(row.item_slug)
            subject = item.subject if item else run.subject
        else:
            continue
        if not (user.id == owner_id or sees_subject(user, subject)):
            continue
        path = UPLOAD_DIR / name
        if path.is_file() and not path.is_symlink() and path.resolve().parent == UPLOAD_DIR.resolve():
            return FileResponse(path, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    raise missing
