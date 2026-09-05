from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..config import BANK_DIR, LOCAL_BANK_DIR, ensure_dirs
from ..constants import CONTAINER_TYPES, DEFAULT_POINTS, DIFFICULTIES, SUBJECTS, TYPES, grade_label


class BankError(Exception):
    pass


@dataclass
class Part:
    id: str
    type: str
    stem: str
    points: float
    choices: list[dict[str, str]] = field(default_factory=list)
    answer: Any = None
    reference: str | None = None
    rubric: list[dict[str, Any]] = field(default_factory=list)
    tolerance: float = 0.0
    unit: str = ""
    allow_photo: bool = False

    def public(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "stem": self.stem,
            "points": self.points,
            "allow_photo": self.allow_photo,
        }
        if self.choices:
            data["choices"] = [{"id": c["id"], "text": c["text"]} for c in self.choices]
        if self.unit:
            data["unit"] = self.unit
        return data

    def editor(self) -> dict[str, Any]:
        answer: Any = self.answer
        if self.type == "blank":
            if isinstance(self.answer, list):
                answer = [str(x) for x in self.answer if str(x).strip()]
            elif self.answer is None or str(self.answer).strip() == "":
                answer = []
            else:
                answer = [str(self.answer)]
        elif self.type == "multiple":
            if isinstance(self.answer, list):
                answer = [str(x) for x in self.answer]
            elif self.answer:
                answer = [str(self.answer)]
            else:
                answer = []
        elif self.type == "single":
            answer = "" if self.answer is None else str(self.answer)
        return {
            "id": self.id,
            "type": self.type,
            "type_name": TYPES.get(self.type, self.type),
            "stem": self.stem,
            "points": self.points,
            "choices": [{"id": c["id"], "text": c["text"]} for c in self.choices],
            "answer": answer,
            "reference": self.reference or "",
            "rubric": [
                {"id": str(r.get("id") or "item"), "points": float(r.get("points") or 0), "require": str(r.get("require") or "")}
                for r in self.rubric
            ],
            "tolerance": self.tolerance,
            "unit": self.unit,
            "allow_photo": self.allow_photo,
        }


@dataclass
class Item:
    slug: str
    title: str
    subject: str
    grade: int
    difficulty: str
    type: str
    tags: list[str]
    points: float
    left_md: str
    parts: list[Part]
    source: str
    allow_photo: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "subject": self.subject,
            "subject_name": SUBJECTS.get(self.subject, self.subject),
            "grade": self.grade,
            "difficulty": self.difficulty,
            "type": self.type,
            "tags": self.tags,
            "points": self.points,
            "left_md": self.left_md,
            "allow_photo": self.allow_photo or any(p.allow_photo for p in self.parts),
            "parts": [p.public() for p in self.parts],
            "source": self.source,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "subject": self.subject,
            "subject_name": SUBJECTS.get(self.subject, self.subject),
            "grade": self.grade,
            "difficulty": self.difficulty,
            "type": self.type,
            "tags": self.tags,
            "points": self.points,
            "source": self.source,
            "source_name": "本机改过" if self.source == "local" else "题库",
            "type_name": TYPES.get(self.type, self.type),
            "difficulty_name": DIFFICULTIES.get(self.difficulty, self.difficulty),
            "grade_name": grade_label(self.grade),
        }

    def editor(self) -> dict[str, Any]:
        data = self.summary()
        data.update(
            {
                "left_md": self.left_md,
                "allow_photo": self.allow_photo,
                "parts": [p.editor() for p in self.parts],
            }
        )
        return data


def _read_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BankError("题目文件不是一份完整题")
    return raw


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _part_from_dict(raw: dict[str, Any], fallback_id: str, default_photo: bool = False) -> Part:
    ptype = str(raw.get("type") or "single")
    points = float(raw.get("points") or DEFAULT_POINTS.get(ptype, 5))
    choices = []
    for c in raw.get("choices") or []:
        if isinstance(c, dict) and c.get("id") is not None:
            choices.append({"id": str(c["id"]), "text": str(c.get("text") or "")})
    rubric = []
    for row in raw.get("rubric") or []:
        if isinstance(row, dict):
            rubric.append(
                {
                    "id": str(row.get("id") or "item"),
                    "points": float(row.get("points") or 0),
                    "require": str(row.get("require") or ""),
                }
            )
    return Part(
        id=str(raw.get("id") or fallback_id),
        type=ptype,
        stem=str(raw.get("stem") or ""),
        points=points,
        choices=choices,
        answer=raw.get("answer"),
        reference=raw.get("reference"),
        rubric=rubric,
        tolerance=float(raw.get("tolerance") or 0),
        unit=str(raw.get("unit") or ""),
        allow_photo=bool(raw.get("allow_photo", default_photo and ptype in ("short", "essay"))),
    )


def item_from_dict(raw: dict[str, Any], source: str, slug_hint: str | None = None) -> Item:
    slug = str(raw.get("slug") or slug_hint or "").strip()
    if not slug:
        raise BankError("题目没有名字，已跳过")
    subject = str(raw.get("subject") or "chinese")
    if subject not in SUBJECTS:
        raise BankError("科目不对")
    itype = str(raw.get("type") or "single")
    grade = int(raw.get("grade") or 7)
    difficulty = str(raw.get("difficulty") or "medium")
    title = str(raw.get("title") or slug)
    tags = []
    for t in _as_list(raw.get("tags")):
        name = str(t).strip()
        if name and name not in tags:
            tags.append(name)
    allow_photo = bool(raw.get("allow_photo", itype == "steps"))
    left = str(raw.get("passage") or raw.get("stem") or "")
    parts_raw = raw.get("parts")
    parts: list[Part] = []
    if isinstance(parts_raw, list) and parts_raw:
        for i, row in enumerate(parts_raw, start=1):
            if isinstance(row, dict):
                parts.append(_part_from_dict(row, f"{i:02d}", default_photo=allow_photo))
    elif itype in CONTAINER_TYPES:
        raise BankError("材料题或过程题缺少小问")
    else:
        part_raw = dict(raw)
        part_raw["id"] = "main"
        part_raw["stem"] = str(raw.get("prompt") or "")
        parts.append(_part_from_dict(part_raw, "main", default_photo=allow_photo))
    points = float(raw.get("points") or sum(p.points for p in parts) or DEFAULT_POINTS.get(itype, 5))
    return Item(
        slug=slug,
        title=title,
        subject=subject,
        grade=grade,
        difficulty=difficulty,
        type=itype,
        tags=tags,
        points=points,
        left_md=left,
        parts=parts,
        source=source,
        allow_photo=allow_photo,
    )


def _load_dir(folder: Path, source: str) -> Item:
    meta_path = folder / "meta.yaml"
    raw = _read_yaml(meta_path) if meta_path.exists() else {}
    raw.setdefault("slug", folder.name)
    stem_file = folder / "stem.md"
    passage_file = folder / "passage.md"
    if passage_file.exists() and not raw.get("passage"):
        raw["passage"] = passage_file.read_text(encoding="utf-8")
    if stem_file.exists() and not raw.get("stem"):
        raw["stem"] = stem_file.read_text(encoding="utf-8")
    parts_dir = folder / "parts"
    if parts_dir.is_dir() and not raw.get("parts"):
        rows = []
        for p in sorted(parts_dir.glob("*.yaml")):
            row = _read_yaml(p)
            row.setdefault("id", p.stem)
            rows.append(row)
        raw["parts"] = rows
    return item_from_dict(raw, source, folder.name)


class Bank:
    def __init__(self) -> None:
        self.items: dict[str, Item] = {}
        self.errors: list[str] = []

    def reload(self) -> None:
        ensure_dirs()
        found: dict[str, Item] = {}
        errors: list[str] = []

        def absorb(item: Item) -> None:
            found[item.slug] = item

        def walk(root: Path, source: str) -> None:
            if not root.exists():
                return
            for path in sorted(root.iterdir()):
                try:
                    if path.is_dir() and (
                        (path / "meta.yaml").exists()
                        or (path / "stem.md").exists()
                        or (path / "passage.md").exists()
                    ):
                        absorb(_load_dir(path, source))
                    elif path.suffix.lower() in {".yaml", ".yml"}:
                        absorb(item_from_dict(_read_yaml(path), source, path.stem))
                except Exception:
                    errors.append(f"{path.name} 没能读进去")

        walk(BANK_DIR, "git")
        walk(LOCAL_BANK_DIR, "local")
        self.items = found
        self.errors = errors

    def get(self, slug: str) -> Item:
        item = self.items.get(slug)
        if not item:
            raise BankError("找不到这道题")
        return item

    def list(
        self,
        subject: str | None = None,
        grade: int | None = None,
        difficulty: str | None = None,
        types: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[Item]:
        rows = list(self.items.values())
        if subject:
            rows = [i for i in rows if i.subject == subject]
        if grade:
            rows = [i for i in rows if i.grade == grade]
        if difficulty:
            rows = [i for i in rows if i.difficulty == difficulty]
        if types:
            allowed = set(types)
            rows = [i for i in rows if i.type in allowed]
        if tags:
            need = [t for t in tags if t]
            rows = [i for i in rows if all(t in i.tags for t in need)]
        rows.sort(key=lambda i: (i.subject, i.grade, i.slug))
        return rows

    def counts_by_subject(self, grade: int | None = None) -> dict[str, int]:
        counts = {key: 0 for key in SUBJECTS}
        for item in self.items.values():
            if grade and item.grade != grade:
                continue
            if item.subject in counts:
                counts[item.subject] += 1
        return counts


bank = Bank()
