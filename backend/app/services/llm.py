from __future__ import annotations

import base64
import json
import math
import mimetypes
import re
from pathlib import Path
from typing import Any

import httpx

from ..config import DEFAULT_LLM_BASE_URL, UPLOAD_DIR, llm_settings
from .bank import Item, Part
from .grade_jobs import enqueue, start_worker


LLM_FAIL_PREFIX = "模型这次没评上："
_GRADE_TIMEOUT = 180.0
_PING_TIMEOUT = 45.0


def _strip_think(text: str) -> str:
    text = text or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    if re.search(r"</think>", text, flags=re.I):
        text = re.split(r"</think>", text, flags=re.I)[-1]
    text = re.sub(r"<think>.*", "", text, flags=re.S | re.I)
    return text.strip()


def _json_blobs(text: str) -> list[str]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
        text = re.sub(r"```\s*$", "", text).strip()
    blobs: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        start = text.find("{", i)
        if start < 0:
            break
        depth = 0
        in_str = False
        esc = False
        end = -1
        for j in range(start, n):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end < 0:
            break
        blobs.append(text[start : end + 1])
        i = end + 1
    return blobs


def _loads_loose(raw: str) -> dict[str, Any] | None:
    candidates = [raw, re.sub(r",\s*([}\]])", r"\1", raw)]
    for blob in candidates:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
            return {"items": data}
    return None


def _extract_json(text: str) -> dict[str, Any] | None:
    text = _strip_think(text)
    direct = _loads_loose(text.strip())
    if direct:
        return direct
    scored: list[tuple[int, dict[str, Any]]] = []
    for blob in _json_blobs(text):
        data = _loads_loose(blob)
        if not data:
            continue
        keys = {str(k).lower() for k in data}
        rank = 0
        if "items" in keys or "分项" in keys:
            rank += 4
        if keys & {"total", "score", "总分", "分数"}:
            rank += 3
        if keys & {"comment", "评语"}:
            rank += 1
        scored.append((rank, data))
    if not scored:
        return None
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[0][1]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            return None
    else:
        text = str(value).strip().replace("，", ".")
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*分?", text):
            return None
        try:
            number = float(text.removesuffix("分").strip())
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _pick(data: dict[str, Any], *names: str) -> Any:
    lower = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        if name in data:
            return data[name]
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _coerce_grade(parsed: dict[str, Any], part: Part) -> dict[str, Any] | None:
    rubric = list(part.rubric or [])
    has_rubric = bool(rubric)
    if not rubric:
        rubric = [{"id": "total", "points": part.points, "require": ""}]
    max_by_id = {str(row["id"]): float(row["points"]) for row in rubric}
    if (not math.isfinite(float(part.points)) or part.points <= 0 or len(max_by_id) != len(rubric)
            or any(not math.isfinite(cap) or cap <= 0 for cap in max_by_id.values())):
        return None
    claimed = _as_float(_pick(parsed, "total", "score", "总分", "分数"))
    if claimed is None or claimed < 0 or claimed > float(part.points):
        return None
    comment = str(_pick(parsed, "comment", "评语", "reason", "说明") or "")
    raw_items = _pick(parsed, "items", "分项", "scores")
    if raw_items is None and not has_rubric:
        raw_items = [{"id": "total", "score": claimed, "reason": comment}]
    if isinstance(raw_items, dict):
        raw_items = [{"id": key, **(value if isinstance(value, dict) else {"score": value})}
                     for key, value in raw_items.items()]
    if not isinstance(raw_items, list):
        return None
    cleaned: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in raw_items:
        if not isinstance(row, dict):
            return None
        rid = str(_pick(row, "id", "item", "name", "要点") or "").strip()
        if rid not in max_by_id or rid in used:
            return None
        score = _as_float(_pick(row, "score", "points", "分", "分数"))
        if score is None or score < 0 or score > max_by_id[rid]:
            return None
        used.add(rid)
        cleaned.append({"id": rid, "score": score,
                        "reason": str(_pick(row, "reason", "comment", "评语", "说明") or "")})
    if used != set(max_by_id):
        return None
    total = sum(row["score"] for row in cleaned)
    if ((total > float(part.points) and not math.isclose(total, float(part.points), rel_tol=0, abs_tol=1e-9))
            or not math.isclose(claimed, total, rel_tol=0, abs_tol=1e-9)):
        return None
    if not comment.strip():
        comment = "；".join(row["reason"].strip() for row in cleaned if row["reason"].strip())
    return {"items": cleaned, "total": claimed, "comment": comment.strip()}


def _image_part(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = path.read_bytes()
    if not data:
        return None
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _messages(item: Item, part: Part, answer_text: str, photos: list[str], vision: bool) -> list[dict[str, Any]]:
    rubric_txt = "\n".join(
        f"- {row['id']}: 满分 {row['points']}。要求：{row['require']}" for row in part.rubric
    ) or f"- total: 满分 {part.points}。按参考答案酌情给分"
    ids = ", ".join(str(row["id"]) for row in (part.rubric or [{"id": "total"}]))
    system = (
        "你是家庭作业评分助手。只评这一问的主观作答。"
        "不要输出思考过程，不要 Markdown 围栏，不要解释。"
        "只输出一个 JSON 对象。"
        f'格式：{{"items":[{{"id":"...","score":0,"reason":"..."}}],"total":0,"comment":"..."}}。'
        f"items 的 id 必须是：{ids}。"
        "total 必须等于 items 分数之和，每项不超过该条满分。"
        "comment 是给学生看的评语，必须写一两句：对在哪里、扣在哪里。不要提密钥。"
    )
    text = (
        f"科目：{item.subject}\n题型：{part.type}\n"
        f"材料或题干：\n{item.left_md}\n\n"
        f"这一问：\n{part.stem}\n\n"
        f"参考答案：\n{part.reference or ''}\n\n"
        f"评分细则：\n{rubric_txt}\n\n"
        f"学生文字作答：\n{answer_text or '（没有文字）'}\n"
    )
    user: Any
    if vision and photos:
        content: list[dict[str, Any]] = [{"type": "text", "text": text + "\n下面是演算纸照片。"}]
        for rel in photos:
            path = (UPLOAD_DIR / rel).resolve()
            if not path.is_relative_to(UPLOAD_DIR.resolve()):
                raise ValueError("图片路径无效，请人工评分")
            img = _image_part(path)
            if not img:
                raise ValueError("作答图片无法读取，请人工评分")
            content.append(img)
        user = {"role": "user", "content": content}
    else:
        user = {"role": "user", "content": text}
    return [{"role": "system", "content": system}, user]


def _auth_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def list_remote_models(base_url: str = "", api_key: str = "") -> list[str]:
    root = (base_url or DEFAULT_LLM_BASE_URL).rstrip("/")
    url = root + "/models"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_auth_headers(api_key))
        resp.raise_for_status()
        data = resp.json()
    names: list[str] = []
    if isinstance(data, dict):
        for row in data.get("data") or []:
            if isinstance(row, dict) and row.get("id"):
                names.append(str(row["id"]))
        for row in data.get("models") or []:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("model") or row.get("id")
            if name:
                names.append(str(name))
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _thinking_variants(enable_thinking: bool, reasoning_effort: str = "") -> list[dict[str, Any]]:
    """Flags to turn thinking off or down. First entry is preferred; later ones drop fields some hosts reject.

    - OpenAI Chat Completions: reasoning_effort = none | minimal | low | medium | high
    - Aliyun/Qwen HTTP: enable_thinking at the top of the JSON body (not extra_body)
    - vLLM / SGLang / llama.cpp: chat_template_kwargs.enable_thinking
    """
    effort = (reasoning_effort or "").strip().lower()
    if effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        effort = "none" if not enable_thinking else ""
    if not enable_thinking:
        effort = "none"
        return [
            {
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "reasoning_effort": "none",
            },
            {"enable_thinking": False, "reasoning_effort": "none"},
            {"enable_thinking": False},
            {"reasoning_effort": "none"},
            {},
        ]
    extras: dict[str, Any] = {
        "enable_thinking": True,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    if effort:
        extras["reasoning_effort"] = effort
        return [
            extras,
            {"enable_thinking": True, "reasoning_effort": effort},
            {"reasoning_effort": effort},
            {"enable_thinking": True},
            {},
        ]
    return [extras, {"enable_thinking": True}, {}]


def _request_variants(enable_thinking: bool, reasoning_effort: str, want_json: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for extra in _thinking_variants(enable_thinking, reasoning_effort):
        options = [{**extra, "response_format": {"type": "json_object"}}, extra] if want_json else [extra]
        for row in options:
            key = json.dumps(row, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out


def _assistant_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    msg: dict[str, Any] = {}
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        choice = {}
    if isinstance(choice, dict):
        maybe_msg = choice.get("message")
        if isinstance(maybe_msg, dict):
            msg = maybe_msg
        text = choice.get("text")
        if text:
            chunks.append(str(text))
    if msg:
        for key in ("content", "reasoning_content", "reasoning"):
            value = msg.get(key)
            if value:
                chunks.append(str(value))
    joined = "\n".join(chunks)
    visible = _strip_think(str(msg.get("content") or ""))
    if visible:
        return visible
    return _strip_think(joined)


def _post_chat(
    url: str,
    headers: dict[str, str],
    model: str,
    messages: list[dict[str, Any]],
    enable_thinking: bool,
    reasoning_effort: str = "",
    temperature: float = 0,
    max_tokens: int | None = None,
    timeout: float = 60.0,
    want_json: bool = False,
) -> dict[str, Any]:
    base: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        base["max_tokens"] = max_tokens
    last_error: Exception | None = None
    with httpx.Client(timeout=timeout) as client:
        for extra in _request_variants(enable_thinking, reasoning_effort, want_json):
            try:
                resp = client.post(url, headers=headers, json={**base, **extra})
                if resp.status_code == 400:
                    last_error = httpx.HTTPStatusError("bad request", request=resp.request, response=resp)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 400:
                    last_error = exc
                    continue
                raise
            except Exception as exc:
                last_error = exc
                break
    if last_error:
        raise last_error
    raise ValueError("模型没有返回")


def ping_llm(
    base_url: str,
    model: str,
    api_key: str = "",
    chat_path: str = "/chat/completions",
    enable_thinking: bool = False,
    reasoning_effort: str = "none",
) -> str:
    if not model:
        raise ValueError("还没有模型名")
    url = (base_url or DEFAULT_LLM_BASE_URL).rstrip("/") + (chat_path or "/chat/completions")
    data = _post_chat(
        url,
        _auth_headers(api_key),
        model,
        [{"role": "user", "content": "只回复一个字：好。不要解释。"}],
        enable_thinking,
        reasoning_effort,
        max_tokens=64,
        timeout=_PING_TIMEOUT,
    )
    text = _assistant_text(data)
    if not text:
        raw = json.dumps(data, ensure_ascii=False)[:240]
        raise ValueError(f"接口通了，但回复空着。原始片段：{raw}")
    return text


def grade_part_attempt(item: Item, part: Part, answer_text: str, photos: list[str]) -> tuple[dict[str, Any] | None, str, bool]:
    """Return (result, error, retryable)."""
    cfg = llm_settings()
    if not (cfg["base_url"] and cfg["model"]):
        return None, "还没有接上模型", False
    if not part.rubric and not part.reference:
        return None, "这问没有细则也没有参考答案，无法自动评", False
    url = cfg["base_url"].rstrip("/") + cfg["chat_path"]
    headers = _auth_headers(cfg["api_key"])

    def call(vision: bool) -> tuple[dict[str, Any] | None, str, bool]:
        try:
            data = _post_chat(
                url,
                headers,
                cfg["model"],
                _messages(item, part, answer_text, photos, vision),
                cfg.get("enable_thinking") == "1",
                cfg.get("reasoning_effort") or ("none" if cfg.get("enable_thinking") != "1" else ""),
                max_tokens=1200,
                timeout=_GRADE_TIMEOUT,
                want_json=True,
            )
        except httpx.TimeoutException:
            return None, "模型超时，可以再评一次", True
        except (ValueError, OSError) as exc:
            return None, f"作答图片或模型响应无法处理：{exc}，请人工评分", False
        except Exception as exc:
            return None, f"没连上模型：{exc}", True
        content = _assistant_text(data)
        if not content:
            return None, "模型回了空内容", True
        parsed = _extract_json(content)
        if not parsed:
            snippet = re.sub(r"\s+", " ", content)[:180]
            return None, f"模型没有给出能用的评分 JSON。回复片段：{snippet}", False
        coerced = _coerce_grade(parsed, part)
        if not coerced:
            snippet = re.sub(r"\s+", " ", content)[:180]
            return None, f"评分 JSON 对不上这一问。回复片段：{snippet}", False
        coerced["photos_used"] = bool(vision and photos)
        return coerced, "", False

    return call(vision=bool(photos))


def grade_part_llm(item: Item, part: Part, answer_text: str, photos: list[str]) -> dict[str, Any] | None:
    result, _err, _retry = grade_part_attempt(item, part, answer_text, photos)
    return result
