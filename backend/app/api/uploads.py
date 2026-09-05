from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import UPLOAD_DIR, ensure_dirs
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..services.answers import get_or_create_answer
from ..services.bank import bank

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

ALLOWED = {".jpg", ".jpeg", ".png", ".webp"}


@router.post("/{context_type}/{context_id}/{slug}/{part_id}")
async def upload_photo(
    context_type: str,
    context_id: int,
    slug: str,
    part_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if context_type not in {"challenge", "paper"}:
        raise HTTPException(400, "不能上传到这里")
    suffix = Path(file.filename or "photo.jpg").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(400, "请拍一张照片")
    data = await file.read()
    if len(data) > 6 * 1024 * 1024:
        raise HTTPException(400, "照片太大了")
    ensure_dirs()
    name = f"{user.id}-{uuid.uuid4().hex}{suffix}"
    dest = UPLOAD_DIR / name
    dest.write_bytes(data)
    item = bank.get(slug)
    row = get_or_create_answer(db, user.id, context_type, context_id, item, part_id)
    photos = json.loads(row.photos_json or "[]")
    photos.append(name)
    row.photos_json = json.dumps(photos[-3:], ensure_ascii=False)
    db.commit()
    return {"ok": True, "photos": json.loads(row.photos_json)}


@router.get("/file/{name}")
def get_file(name: str, _user: User = Depends(get_current_user)) -> FileResponse:
    path = UPLOAD_DIR / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "找不到这张照片")
    return FileResponse(path)
