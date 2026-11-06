"""Conservative blank-answer comparison; never evaluate arbitrary Python."""
from __future__ import annotations

import ast
import math
import re
import unicodedata
from fractions import Fraction
from typing import Any

MAX_LENGTH = 256
_SUB = str.maketrans('₀₁₂₃₄₅₆₇₈₉₊₋₌', '0123456789+-=')
_SUP = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻', '0123456789+-')
_SUP_RE = re.compile(r'[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+')
_NUMERIC_SUBJECTS = {'math', 'physics', 'chemistry'}


def normalize(value: Any) -> str:
    if value is None or isinstance(value, (list, dict, bool)):
        return ''
    text = str(value).strip()
    if not text or len(text) > MAX_LENGTH:
        return ''
    text = _SUP_RE.sub(lambda m: '^' + m.group().translate(_SUP), text).translate(_SUB)
    text = unicodedata.normalize('NFKC', text)
    text = text.translate(str.maketrans({'−':'-', '–':'-', '×':'*', '·':'*', '⋅':'*', '÷':'/', '⟶':'→', '⁄':'/'}))
    # Only the explicitly parenthesized square-root argument has a defined scope.
    text = re.sub(r'√\s*(?=\()', 'sqrt', text)
    text = re.sub(r'\^\s*\(\s*([+-]?\d+)\s*\)', r'^\1', text)
    # Preserve spaces between words/numbers, but ignore spaces around punctuation.
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*([+*/^=()\-→])\s*', r'\1', text)
    return text.strip()


def _expand_percent(text: str) -> str:
    """Bind each percent to its immediately preceding number or parenthesized atom."""
    while '%' in text:
        end = text.index('%')
        if end == 0 or (end + 1 < len(text) and text[end + 1] not in '+-*/^)'):
            raise ValueError
        if text[end - 1] == ')':
            depth = 1
            start = end - 2
            while start >= 0 and depth:
                if text[start] == ')':
                    depth += 1
                elif text[start] == '(':
                    depth -= 1
                start -= 1
            if depth:
                raise ValueError
            start += 1
            if text[max(0, start - 4):start] == 'sqrt':
                start -= 4
        else:
            match = re.search(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$', text[:end])
            if not match:
                raise ValueError
            start = match.start()
        atom = text[start:end]
        text = text[:start] + '(' + atom + '/100)' + text[end + 1:]
        if len(text) > MAX_LENGTH * 4:
            raise ValueError
    return text


def _fraction(text: str) -> Fraction | None:
    if not text or len(text) > MAX_LENGTH:
        return None
    if not re.fullmatch(r'[0-9.eE+*/^()\- sqrt%]+', text):
        return None
    # Python rejects leading zeros in integer literals; canonicalize each numeric token.
    number = re.compile(r'(?<![A-Za-z0-9_.])(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?')
    def canonical(match: re.Match[str]) -> str:
        token = match.group()
        mantissa, marker, exponent = token.lower().partition('e')
        if len(token) > 32 or (marker and abs(int(exponent)) > 30):
            raise ValueError
        if '.' in mantissa:
            before, after = mantissa.split('.', 1)
            mantissa = (str(int(before)) if before else '0') + '.' + after
        else:
            mantissa = str(int(mantissa))
        return mantissa + (('e' + exponent) if marker else '')
    try:
        expression = number.sub(canonical, _expand_percent(text)).replace('^', '**')
        tree = ast.parse(expression, mode='eval')
        if len(list(ast.walk(tree))) > 64:
            return None

        def walk(node: ast.AST, depth: int = 0) -> Fraction:
            if depth > 12:
                raise ValueError
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                segment = ast.get_source_segment(expression, node)
                if not segment or len(segment) > 32:
                    raise ValueError
                result = Fraction(segment)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                result = walk(node.operand, depth + 1)
                if isinstance(node.op, ast.USub): result = -result
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'sqrt' and len(node.args) == 1 and not node.keywords:
                value = walk(node.args[0], depth + 1)
                if value < 0: raise ValueError
                n, d = math.isqrt(value.numerator), math.isqrt(value.denominator)
                if n*n != value.numerator or d*d != value.denominator: raise ValueError
                result = Fraction(n, d)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
                left, right = walk(node.left, depth + 1), walk(node.right, depth + 1)
                if isinstance(node.op, ast.Add): result = left + right
                elif isinstance(node.op, ast.Sub): result = left - right
                elif isinstance(node.op, ast.Mult): result = left * right
                elif isinstance(node.op, ast.Div): result = left / right
                else:
                    if right.denominator != 1 or abs(right.numerator) > 30:
                        raise ValueError
                    result = left ** right.numerator
            else:
                raise ValueError
            if result.numerator.bit_length() > 256 or result.denominator.bit_length() > 256:
                raise ValueError
            return result
        return walk(tree.body)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError):
        return None


def numeric_value(value: Any) -> float | None:
    """Read a numeric answer, including bounded fractions and percentages."""
    raw = value.replace('，', '.') if isinstance(value, str) else value
    text = normalize(raw)
    if not text:
        return None
    if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', text):
        try:
            result = float(text)
            return result if math.isfinite(result) else None
        except (ValueError, OverflowError):
            return None
    result = _fraction(text)
    return float(result) if result is not None else None


def equivalent_blank(value: Any, accepted: Any, subject: str | None) -> bool:
    got = normalize(value)
    if subject == 'english':
        got = re.sub(r"(?<=[A-Za-z])[‘’ʼ]", "'", got)
    if not got:
        return False
    candidates = accepted if isinstance(accepted, list) else [accepted]
    for candidate in candidates:
        expected = normalize(candidate)
        if subject == 'english':
            expected = re.sub(r"(?<=[A-Za-z])[‘’ʼ]", "'", expected)
        if not expected:
            continue
        if subject in _NUMERIC_SUBJECTS:
            left, right = _fraction(got), _fraction(expected)
            if left is not None and right is not None:
                if left == right: return True
                continue
            # An invalid pure arithmetic expression is never accepted verbatim.
            if re.fullmatch(r'[0-9.eE+*/^()\- %]+', got) and re.fullmatch(r'[0-9.eE+*/^()\- %]+', expected):
                continue
        if got == expected:
            return True
    return False
