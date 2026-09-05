from __future__ import annotations

import base64
import json
import mimetypes
import queue
import re
import threading
from pathlib import Path
from typing import Any

import httpx

from ..config import DEFAULT_LLM_BASE_URL, UPLOAD_DIR, llm_configured, llm_settings
from .bank import Item, Part


_work: queue.Queue[tuple[int, str, str, list[str]]] = queue.Queue()
_started = False


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _image_part(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _messages(item: Item, part: Part, answer_text: str, photos: list[str], vision: bool) -> list[dict[str, Any]]:
    rubric_txt = "\n".join(
        f"- {row['id']}: 满分 {row['points']}。要求：{row['require']}" for row in part.rubric
    ) or f"- total: 满分 {part.points}。按参考答案酌情给分"
    system = (
        "你是家庭作业评分助手。只评这一问的主观作答。"
        "必须只输出一段 JSON，不要Markdown围栏以外的说明。"
        '格式：{"items":[{"id":"...","score":0,"reason":"..."}],"total":0,"comment":"..."}。'
        "total 必须等于 items 分数之和，每项不超过该条满分。不要提密钥。"
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
        for rel in photos[:3]:
            img = _image_part(UPLOAD_DIR / rel)
            if img:
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


def _assistant_text(data: dict[str, Any]) -> str:
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    text = str((msg or {}).get("content") or "")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    return text.strip()


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
) -> dict[str, Any]:
    base: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        base["max_tokens"] = max_tokens
    last_error: Exception | None = None
    with httpx.Client(timeout=timeout) as client:
        for extra in _thinking_variants(enable_thinking, reasoning_effort):
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
        [{"role": "user", "content": "只回复一个字：好"}],
        enable_thinking,
        reasoning_effort,
        max_tokens=16,
    )
    text = _assistant_text(data)
    if not text:
        raise ValueError("接口通了，但返回格式不是对话")
    return text


def grade_part_llm(item: Item, part: Part, answer_text: str, photos: list[str]) -> dict[str, Any] | None:
    cfg = llm_settings()
    if not (cfg["base_url"] and cfg["model"]):
        return None
    if not part.rubric and not part.reference:
        return None
    url = cfg["base_url"].rstrip("/") + cfg["chat_path"]
    headers = _auth_headers(cfg["api_key"])

    def call(vision: bool) -> dict[str, Any] | None:
        try:
            data = _post_chat(
                url,
                headers,
                cfg["model"],
                _messages(item, part, answer_text, photos, vision),
                cfg.get("enable_thinking") == "1",
                cfg.get("reasoning_effort") or ("none" if cfg.get("enable_thinking") != "1" else ""),
            )
        except Exception:
            return None
        content = _assistant_text(data)
        parsed = _extract_json(str(content or ""))
        if not parsed:
            return None
        items = parsed.get("items") or []
        if not isinstance(items, list) or not items:
            return None
        total = 0.0
        max_by_id = {row["id"]: float(row["points"]) for row in part.rubric}
        if not max_by_id:
            max_by_id = {"total": float(part.points)}
        cleaned = []
        for row in items:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id") or "total")
            cap = max_by_id.get(rid, part.points)
            try:
                score = float(row.get("score") or 0)
            except (TypeError, ValueError):
                return None
            if score < 0 or score > cap + 1e-6:
                return None
            score = min(score, cap)
            total += score
            cleaned.append({"id": rid, "score": score, "reason": str(row.get("reason") or "")})
        claimed = parsed.get("total")
        try:
            claimed_f = float(claimed)
        except (TypeError, ValueError):
            return None
        if abs(claimed_f - total) > 0.05:
            return None
        if total > part.points + 1e-6:
            return None
        return {
            "items": cleaned,
            "total": round(total, 2),
            "comment": str(parsed.get("comment") or ""),
            "photos_used": bool(vision and photos),
        }

    result = call(vision=bool(photos))
    if result is None and photos:
        result = call(vision=False)
        if result is not None:
            result["comment"] = (result.get("comment") or "") + "（图片未评）"
    return result


def start_worker() -> None:
    global _started
    if _started:
        return
    _started = True

    def loop() -> None:
        from datetime import datetime

        from ..db import SessionLocal
        from ..models import ItemAnswer
        from .bank import bank
        from .grade import load_value

        while True:
            answer_id, slug, part_id, photos = _work.get()
            try:
                db = SessionLocal()
                row = db.get(ItemAnswer, answer_id)
                if not row or row.status == "overridden":
                    db.close()
                    continue
                try:
                    item = bank.get(slug)
                    part = next(p for p in item.parts if p.id == part_id)
                except Exception:
                    db.close()
                    continue
                text = str(load_value(row.value_json) or "")
                result = grade_part_llm(item, part, text, photos)
                row = db.get(ItemAnswer, answer_id)
                if not row or row.status == "overridden":
                    db.close()
                    continue
                if result:
                    row.score = float(result["total"])
                    row.llm_json = json.dumps(result, ensure_ascii=False)
                    row.llm_comment = result.get("comment")
                    row.status = "graded"
                    row.graded_at = datetime.utcnow()
                else:
                    row.status = "pending"
                db.commit()
                db.close()
            except Exception:
                pass

    threading.Thread(target=loop, name="llm-grade", daemon=True).start()
    _requeue_pending()


def _requeue_pending() -> None:
    if not llm_configured():
        return
    try:
        from sqlalchemy import select

        from ..db import SessionLocal
        from ..models import ItemAnswer

        db = SessionLocal()
        try:
            rows = db.scalars(select(ItemAnswer).where(ItemAnswer.status == "pending")).all()
            for row in rows:
                photos = []
                try:
                    photos = json.loads(row.photos_json or "[]")
                except json.JSONDecodeError:
                    photos = []
                _work.put((row.id, row.item_slug, row.part_id, photos))
        finally:
            db.close()
    except Exception:
        pass


def enqueue(answer_id: int, slug: str, part_id: str, photos: list[str]) -> None:
    if not llm_configured():
        return
    start_worker()
    _work.put((answer_id, slug, part_id, photos))
