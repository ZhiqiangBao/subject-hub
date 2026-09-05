from __future__ import annotations

import re
import time
import zipfile
from io import BytesIO
from typing import Any

import yaml

from ..config import LOCAL_BANK_DIR, ensure_dirs
from ..constants import CONTAINER_TYPES, DEFAULT_POINTS, SUBJECTIVE_TYPES, SUBJECTS
from .bank import BankError, Item, item_from_dict


FENCE = re.compile(r"```(?:ya?ml)?\s*\r?\n([\s\S]*?)```", re.I)


def _safe_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9\-]+", "-", text.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or f"item-{int(time.time())}"


def parse_yaml_documents(text: str) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    chunks = FENCE.findall(text)
    if not chunks:
        chunks = [text]
    for chunk in chunks:
        try:
            loaded = list(yaml.safe_load_all(chunk))
        except yaml.YAMLError:
            continue
        for raw in loaded:
            if isinstance(raw, dict) and (raw.get("stem") or raw.get("passage") or raw.get("parts") or raw.get("type")):
                docs.append(raw)
    return docs


def items_from_text(text: str, source: str = "local") -> list[Item]:
    items: list[Item] = []
    for i, raw in enumerate(parse_yaml_documents(text), start=1):
        raw = dict(raw)
        if not raw.get("slug"):
            raw["slug"] = _safe_slug(str(raw.get("title") or f"import-{int(time.time())}-{i}"))
        try:
            items.append(item_from_dict(raw, source, raw["slug"]))
        except BankError:
            continue
    return items


def items_from_zip(data: bytes) -> list[Item]:
    items: list[Item] = []
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = zf.namelist()
        yaml_names = [n for n in names if n.lower().endswith((".yaml", ".yml")) and not n.endswith("/")]
        for name in yaml_names:
            try:
                text = zf.read(name).decode("utf-8")
            except UnicodeDecodeError:
                continue
            items.extend(items_from_text(text))
    return items


def save_item(item: Item) -> Path:
    ensure_dirs()
    path = LOCAL_BANK_DIR / f"{item.slug}.yaml"
    payload: dict[str, Any] = {
        "slug": item.slug,
        "title": item.title,
        "subject": item.subject,
        "grade": item.grade,
        "difficulty": item.difficulty,
        "type": item.type,
        "tags": item.tags,
        "points": item.points,
        "allow_photo": item.allow_photo,
    }
    if item.type in {"passage", "steps"}:
        if item.type == "passage":
            payload["passage"] = item.left_md
        else:
            payload["stem"] = item.left_md
        parts = []
        for part in item.parts:
            row: dict[str, Any] = {
                "id": part.id,
                "type": part.type,
                "stem": part.stem,
                "points": part.points,
            }
            if part.choices:
                row["choices"] = part.choices
            if part.answer is not None:
                row["answer"] = part.answer
            if part.reference:
                row["reference"] = part.reference
            if part.rubric:
                row["rubric"] = part.rubric
            if part.tolerance:
                row["tolerance"] = part.tolerance
            if part.unit:
                row["unit"] = part.unit
            if part.allow_photo:
                row["allow_photo"] = True
            parts.append(row)
        payload["parts"] = parts
    else:
        payload["stem"] = item.left_md
        part = item.parts[0]
        payload["type"] = part.type
        if part.choices:
            payload["choices"] = part.choices
        if part.answer is not None:
            payload["answer"] = part.answer
        if part.reference:
            payload["reference"] = part.reference
        if part.rubric:
            payload["rubric"] = part.rubric
        if part.tolerance:
            payload["tolerance"] = part.tolerance
        if part.unit:
            payload["unit"] = part.unit
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _part_payload(part: dict[str, Any]) -> dict[str, Any]:
    ptype = str(part.get("type") or "short")
    row: dict[str, Any] = {
        "id": str(part.get("id") or "main"),
        "type": ptype,
        "stem": str(part.get("stem") or ""),
        "points": float(part.get("points") or DEFAULT_POINTS.get(ptype, 5)),
        "allow_photo": bool(part.get("allow_photo")),
    }
    if ptype in {"single", "multiple"}:
        choices = []
        for c in part.get("choices") or []:
            if isinstance(c, dict) and c.get("id") is not None:
                text = str(c.get("text") or "").strip()
                if text:
                    choices.append({"id": str(c["id"]), "text": text})
        if len(choices) < 2:
            raise BankError("选择题至少要有两个选项")
        ids = {c["id"] for c in choices}
        row["choices"] = choices
        if ptype == "single":
            ans = str(part.get("answer") or "").strip()
            if ans not in ids:
                raise BankError("请点一个正确答案")
            row["answer"] = ans
        else:
            raw_ans = part.get("answer") or []
            if not isinstance(raw_ans, list):
                raw_ans = [raw_ans]
            picked = [str(x) for x in raw_ans if str(x) in ids]
            if not picked:
                raise BankError("请点出正确答案")
            row["answer"] = picked
    elif ptype == "blank":
        raw_ans = part.get("answer") or []
        if not isinstance(raw_ans, list):
            raw_ans = [raw_ans]
        forms = [str(x).strip() for x in raw_ans if str(x).strip()]
        if not forms:
            raise BankError("请至少写一种正确写法")
        row["answer"] = forms
    elif ptype == "numeric":
        try:
            row["answer"] = float(part.get("answer"))
        except (TypeError, ValueError):
            raise BankError("得数要是数字") from None
        row["tolerance"] = float(part.get("tolerance") or 0)
        row["unit"] = str(part.get("unit") or "")
    elif ptype in SUBJECTIVE_TYPES:
        row["reference"] = str(part.get("reference") or "")
        rubric = []
        for i, item in enumerate(part.get("rubric") or [], start=1):
            if not isinstance(item, dict):
                continue
            require = str(item.get("require") or "").strip()
            if not require:
                continue
            rubric.append(
                {
                    "id": str(item.get("id") or f"r{i}"),
                    "points": float(item.get("points") or 0),
                    "require": require,
                }
            )
        if not rubric and not row["reference"]:
            raise BankError("主观题请写参考答案或评分细则")
        if not rubric:
            rubric = [{"id": "content", "points": row["points"], "require": "意思对、语句通顺"}]
        row["rubric"] = rubric
    return row


def item_from_editor(slug: str, subject: str, itype: str, payload: dict[str, Any]) -> Item:
    if subject not in SUBJECTS:
        raise BankError("科目不对")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise BankError("请写题目名字")
    left = str(payload.get("left_md") or "")
    if not left.strip():
        raise BankError("请写材料" if itype == "passage" else "请写题目")
    raw: dict[str, Any] = {
        "slug": slug,
        "title": title,
        "subject": subject,
        "grade": int(payload.get("grade") or 7),
        "difficulty": str(payload.get("difficulty") or "medium"),
        "type": itype,
        "tags": [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()],
        "allow_photo": bool(payload.get("allow_photo")),
    }
    if payload.get("points") is not None and payload.get("points") != "":
        raw["points"] = float(payload["points"])
    parts_in = payload.get("parts") or []
    if not isinstance(parts_in, list) or not parts_in:
        raise BankError("题目不完整")
    if itype == "passage":
        raw["passage"] = left
        raw["parts"] = [_part_payload(p) for p in parts_in if isinstance(p, dict)]
    elif itype == "steps":
        raw["stem"] = left
        raw["parts"] = [_part_payload(p) for p in parts_in if isinstance(p, dict)]
    else:
        part_raw = _part_payload(parts_in[0])
        part_raw.pop("id", None)
        part_raw.pop("stem", None)
        raw.update(part_raw)
        raw["type"] = itype
        raw["stem"] = left
    if itype in CONTAINER_TYPES and not raw.get("parts"):
        raise BankError("材料题或过程题缺少小问")
    return item_from_dict(raw, "local", slug)


CHOICE_LINE = re.compile(r"^([A-D])[\.．、]\s*(.+)$", re.I | re.M)


def plain_item(
    subject: str,
    itype: str,
    stem: str,
    answer: str,
    grade: int | None,
    difficulty: str,
    title: str,
    tags: list[str] | None = None,
) -> Item:
    if subject not in SUBJECTS:
        subject = "chinese"
    if itype not in OBJECTIVE_TYPES and itype not in {"short", "essay"}:
        itype = "short"
    slug = _safe_slug(title or f"{subject}-{int(time.time())}")
    choices = []
    for match in CHOICE_LINE.finditer(stem):
        choices.append({"id": match.group(1).upper(), "text": match.group(2).strip()})
    if choices and itype == "short":
        itype = "single"
    if itype == "single" and not choices:
        itype = "blank"
    points = float(DEFAULT_POINTS.get(itype, 5))
    raw: dict[str, Any] = {
        "slug": slug,
        "title": title or "练习题",
        "subject": subject,
        "grade": grade or 7,
        "difficulty": difficulty or "medium",
        "type": itype,
        "tags": [str(t).strip() for t in (tags or []) if str(t).strip()],
        "points": points,
        "stem": stem.strip(),
    }
    ans = answer.strip()
    if itype == "single":
        raw["choices"] = choices or [{"id": "A", "text": ans or "选项"}]
        raw["answer"] = ans.upper()[:1] if ans else "A"
    elif itype == "multiple":
        raw["choices"] = choices
        raw["answer"] = [x.strip().upper() for x in re.split(r"[,，\s]+", ans) if x.strip()]
    elif itype == "numeric":
        try:
            raw["answer"] = float(ans.replace("，", "."))
        except ValueError:
            raw["type"] = "blank"
            itype = "blank"
            raw["answer"] = [ans]
    elif itype == "blank":
        raw["answer"] = [x.strip() for x in re.split(r"[,，/]+", ans) if x.strip()] or [ans]
    else:
        raw["reference"] = ans
        raw["rubric"] = [{"id": "content", "points": points, "require": "意思对、语句通顺"}]
    return item_from_dict(raw, "local", slug)
