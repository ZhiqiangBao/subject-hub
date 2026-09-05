from __future__ import annotations

import json
import re
from typing import Any

from ..constants import PAPER_SECTIONS
from ..models import Paper
from .bank import Item

_CN = "一二三四五六七八九十"
_LEAD = re.compile(r"^[一二三四五六七八九十]、\s*")


def section_spec(section_id: str) -> dict[str, Any] | None:
    for row in PAPER_SECTIONS:
        if row["id"] == section_id:
            return row
    return None


def _fmt_points(items: list[Item]) -> str:
    vals = {round(float(i.points), 2) for i in items}
    if len(vals) != 1:
        return "不等"
    value = vals.pop()
    return str(int(value)) if value == int(value) else str(value)


def _fmt_total(items: list[Item]) -> str:
    total = round(sum(float(i.points) for i in items), 2)
    return str(int(total)) if total == int(total) else str(total)


def fill_heading(template: str, items: list[Item], index: int, name: str) -> str:
    body = _LEAD.sub("", (template or "").strip()) or f"{name}（本题共{{count}}小题，每小题{{points}}分）"
    filled = (
        body.replace("{count}", str(len(items)))
        .replace("{points}", _fmt_points(items))
        .replace("{total}", _fmt_total(items))
        .replace("{name}", name)
    )
    prefix = _CN[index] if index < len(_CN) else str(index + 1)
    return f"{prefix}、{filled}"


def paper_layout(paper: Paper) -> list[dict[str, Any]]:
    slugs = json.loads(paper.slugs_json or "[]")
    raw = getattr(paper, "sections_json", None) or ""
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list) and data:
            out = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                part_slugs = [s for s in (row.get("slugs") or []) if s]
                if not part_slugs:
                    continue
                out.append({"heading": str(row.get("heading") or ""), "slugs": part_slugs})
            if out:
                return out
    return [{"heading": "", "slugs": slugs}]


def heading_for_slug(paper: Paper, slug: str) -> str:
    for row in paper_layout(paper):
        if slug in row["slugs"]:
            return str(row.get("heading") or "")
    return ""
