from __future__ import annotations

import json
import re
from typing import Any

from .bank import Part
from .blank import equivalent_blank, numeric_value
from ..constants import OBJECTIVE_TYPES, SUBJECTIVE_TYPES


_SUB_TO_ASCII = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋₌", "0123456789+-=")
_SUP_CHARS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼"
_SUP_ASCII = "0123456789+-="
_LATEX_TO_SYM = (
    ("\\rightleftharpoons", "⇌"),
    ("\\rightarrow", "→"),
    ("\\partial", "∂"),
    ("\\infty", "∞"),
    ("\\times", "×"),
    ("\\cdot", "·"),
    ("\\leq", "≤"),
    ("\\geq", "≥"),
    ("\\neq", "≠"),
    ("\\div", "÷"),
    ("\\pm", "±"),
    ("\\sum", "∑"),
    ("\\prod", "∏"),
    ("\\int", "∫"),
    ("\\pi", "π"),
    ("\\sqrt", "√"),
    ("\\to", "→"),
    ("\\circ", "°"),
)


def _norm_text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    text = text.replace("$$", "").replace("$", "")
    for src, dst in _LATEX_TO_SYM:
        text = text.replace(src, dst)
    text = text.replace("⟶", "→").replace("⋅", "·")

    def sup_run(match: re.Match[str]) -> str:
        return "^" + match.group(0).translate(str.maketrans(_SUP_CHARS, _SUP_ASCII))

    text = re.sub(f"[{_SUP_CHARS}]+", sup_run, text)
    text = text.translate(_SUB_TO_ASCII)
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        return {_norm_text(v) for v in value if str(v).strip()}
    return {_norm_text(x) for x in str(value).replace("，", ",").split(",") if x.strip()}


def grade_objective(part: Part, value: Any, subject: str | None = None) -> float:
    if part.type not in OBJECTIVE_TYPES:
        return 0.0
    if part.type == "single":
        ok = _norm_text(value) == _norm_text(part.answer)
        return part.points if ok else 0.0
    if part.type == "multiple":
        expected = {_norm_text(x) for x in (part.answer or [])}
        got = _as_set(value)
        return part.points if got == expected and expected else 0.0
    if part.type == "blank":
        return part.points if equivalent_blank(value, part.answer, subject) else 0.0
    if part.type == "numeric":
        got = numeric_value(value)
        expected = numeric_value(part.answer)
        if got is None or expected is None:
            return 0.0
        tol = float(part.tolerance or 0)
        return part.points if abs(got - expected) <= max(tol, 1e-9) else 0.0
    return 0.0


def is_objective(part: Part) -> bool:
    return part.type in OBJECTIVE_TYPES


def is_subjective(part: Part) -> bool:
    return part.type in SUBJECTIVE_TYPES


def dump_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def load_value(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw
