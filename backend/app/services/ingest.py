from __future__ import annotations

import hashlib
import math
import re
import tempfile
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import yaml

from ..config import LOCAL_BANK_DIR, ensure_dirs
from ..constants import CONTAINER_TYPES, DEFAULT_POINTS, DIFFICULTIES, OBJECTIVE_TYPES, SUBJECTIVE_TYPES, SUBJECTS, TYPES
from .bank import BankError, Item, item_from_dict


FENCE = re.compile(r"```(?:ya?ml)?\s*\r?\n([\s\S]*?)```", re.I)


MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 100


def checked_slug(value: str) -> str:
    if (not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value)
            or re.fullmatch(r"con|prn|aux|nul|com[0-9]|lpt[0-9]", value)):
        raise BankError("题目标识只能用小写字母、数字和连字符，最长 80 位，不能是系统保留名")
    return value


def _safe_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9\-]+", "-", text.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return (slug or "item")[:48]


class _ImportLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        self.nodes = getattr(self, "nodes", 0) + 1
        self.depth = getattr(self, "depth", 0) + 1
        if self.nodes > 30000 or self.depth > 32 or self.check_event(yaml.AliasEvent):
            raise BankError("题包结构过大或使用了不支持的 YAML 引用")
        try:
            return super().compose_node(parent, index)
        finally:
            self.depth -= 1


def parse_yaml_documents(text: str) -> list[dict[str, Any]]:
    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise BankError("题包超过 2 MB，请拆分后导入")
    docs: list[dict[str, Any]] = []
    chunks = FENCE.findall(text)
    if not chunks:
        chunks = [text]
    for chunk in chunks:
        try:
            for raw in yaml.load_all(chunk, Loader=_ImportLoader):
                if not isinstance(raw, dict):
                    raise BankError("每一份 YAML 都应是一道题目")
                docs.append(raw)
                if len(docs) > MAX_ITEMS:
                    raise BankError("一次最多导入 100 题")
        except (yaml.YAMLError, ValueError, RecursionError) as exc:
            raise BankError("题包 YAML 格式有误，请检查后再试") from exc
    return docs


def items_from_text(text: str, source: str = "local") -> list[Item]:
    items: list[Item] = []
    for i, raw in enumerate(parse_yaml_documents(text), start=1):
        raw = dict(raw)
        if not raw.get("slug"):
            digest = hashlib.sha256(yaml.safe_dump(raw).encode()).hexdigest()[:16]
            raw["slug"] = f"{_safe_slug(str(raw.get('title') or 'item'))}-{digest}"
        try:
            checked_slug(str(raw["slug"]))
            if raw.get("subject") not in SUBJECTS or type(raw.get("grade")) is not int or not 1 <= raw["grade"] <= 12:
                raise BankError("请指定有效的科目和 1～12 年级")
            if raw.get("type") not in TYPES or raw.get("difficulty", "medium") not in DIFFICULTIES:
                raise BankError("题型或难度无效")
            for entry in [raw, *(raw.get("parts") or [])]:
                if not isinstance(entry, dict) or ("points" in entry and (type(entry["points"]) not in (int, float) or not math.isfinite(entry["points"]) or entry["points"] <= 0)):
                    raise BankError("小问或分值无效")
            item = item_from_dict(raw, source, raw["slug"])
            validate_item(item)
            items.append(item)
        except (TypeError, ValueError, OverflowError, AttributeError, BankError) as exc:
            raise BankError(f"第 {i} 道题有误：{exc}") from exc
    return items


def items_from_zip(data: bytes) -> list[Item]:
    items: list[Item] = []
    if len(data) > MAX_IMPORT_BYTES:
        raise BankError("题包超过 2 MB，请拆分后导入")
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            entries = zf.infolist()
            if len(entries) > MAX_ITEMS or sum(e.file_size for e in entries) > MAX_IMPORT_BYTES:
                raise BankError("压缩包展开后过大，请拆分后导入")
            for entry in entries:
                if not entry.is_dir() and entry.filename.lower().endswith((".yaml", ".yml")):
                    items.extend(items_from_text(zf.read(entry).decode("utf-8-sig")))
                    if len(items) > MAX_ITEMS:
                        raise BankError("一次最多导入 100 题")
    except (zipfile.BadZipFile, UnicodeError, RuntimeError, NotImplementedError, OSError) as exc:
        raise BankError("文件不是可读取的 UTF-8 YAML 压缩包") from exc
    return items


def validate_item(item: Item) -> None:
    checked_slug(item.slug)
    if not item.left_md.strip() or not item.parts or item.type not in TYPES:
        raise BankError("请补全题干和小问")
    if len({p.id for p in item.parts}) != len(item.parts):
        raise BankError("小问编号不能重复")
    if not math.isclose(item.points, sum(p.points for p in item.parts), abs_tol=1e-6):
        raise BankError("题目总分与各小问的分值不符")
    if not 1 <= item.grade <= 12 or item.difficulty not in DIFFICULTIES:
        raise BankError("年级或难度无效")
    for part in item.parts:
        if part.type not in OBJECTIVE_TYPES | SUBJECTIVE_TYPES or not math.isfinite(part.points) or part.points <= 0:
            raise BankError("小问题型或分值无效")
        if item.type not in CONTAINER_TYPES and (len(item.parts) != 1 or item.type != part.type):
            raise BankError("题型与小问不符")
        if part.type in {"single", "multiple"}:
            ids = [c["id"] for c in part.choices]
            answers = part.answer if part.type == "multiple" else [part.answer]
            if (len(ids) < 2 or len(set(ids)) != len(ids) or any(not c["text"].strip() for c in part.choices)
                    or not isinstance(answers, list) or not answers or any(str(a) not in ids for a in answers)):
                raise BankError("选项或正确答案无效")
        elif part.type == "blank":
            values = part.answer if isinstance(part.answer, list) else [part.answer]
            if not values or any(type(v) not in (int, float, str) or not str(v).strip() for v in values):
                raise BankError("填空题需要有效答案")
        elif part.type == "numeric":
            if not math.isfinite(float(part.answer)) or not math.isfinite(part.tolerance) or part.tolerance < 0:
                raise BankError("数值答案或误差无效")
        elif not part.reference and not part.rubric:
            raise BankError("主观题需要参考答案或评分细则")
        if part.rubric and (any(not r["require"] or not math.isfinite(r["points"]) or r["points"] <= 0 for r in part.rubric)
                            or not math.isclose(sum(r["points"] for r in part.rubric), part.points, abs_tol=1e-6)):
            raise BankError("评分细则内容或分值不符")


def save_item(item: Item, *, exclusive: bool = False) -> Path:
    validate_item(item)
    ensure_dirs()
    directory = LOCAL_BANK_DIR.resolve()
    path = directory / f"{item.slug}.yaml"
    if path.is_symlink() or path.resolve().parent != directory:
        raise BankError("不能写入题库目录之外")
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
    content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    if exclusive:
        with path.open("x", encoding="utf-8") as output:
            output.write(content)
    else:
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, encoding="utf-8", delete=False) as output:
            tmp = Path(output.name)
            try:
                output.write(content)
            except BaseException:
                output.close()
                tmp.unlink(missing_ok=True)
                raise
        try:
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
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
    slug = f"{_safe_slug(title or subject)}-{uuid.uuid4().hex[:16]}"
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
        raw["answer"] = [x.strip() for x in re.split(r"[,，\n]+", ans) if x.strip()] or [ans]
    else:
        raw["reference"] = ans
        raw["rubric"] = [{"id": "content", "points": points, "require": "意思对、语句通顺"}]
    return item_from_dict(raw, "local", slug)
