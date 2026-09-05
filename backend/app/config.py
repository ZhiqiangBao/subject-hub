from __future__ import annotations

import os
import secrets
from pathlib import Path


ROOT = Path(os.environ.get("SUBJECT_HUB_ROOT", Path(__file__).resolve().parents[2]))
BANK_DIR = Path(os.environ.get("SUBJECT_HUB_BANK", ROOT / "bank"))
DATA_DIR = Path(os.environ.get("SUBJECT_HUB_DATA", ROOT / "data"))
LOCAL_BANK_DIR = DATA_DIR / "local-bank"
UPLOAD_DIR = DATA_DIR / "uploads"
FRONTEND_DIST = ROOT / "frontend" / "dist"
SKILL_PATH = ROOT / "docs" / "author-bank-skill.md"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_BANK_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    BANK_DIR.mkdir(parents=True, exist_ok=True)


LLM_ENV_PATH = DATA_DIR / "llm.env"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8080/v1"
LLM_ENV_KEYS = (
    "SUBJECT_HUB_LLM_BASE_URL",
    "SUBJECT_HUB_LLM_API_KEY",
    "SUBJECT_HUB_LLM_MODEL",
    "SUBJECT_HUB_LLM_CHAT_PATH",
    "SUBJECT_HUB_LLM_ENABLE_THINKING",
    "SUBJECT_HUB_LLM_REASONING_EFFORT",
)


def _parse_llm_file() -> dict[str, str]:
    out: dict[str, str] = {}
    if not LLM_ENV_PATH.is_file():
        return out
    for line in LLM_ENV_PATH.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def llm_settings() -> dict[str, str]:
    file_map = _parse_llm_file()

    def pick(name: str, default: str = "") -> str:
        env = os.environ.get(name, "").strip()
        if env:
            return env
        return (file_map.get(name) or default).strip()

    path = pick("SUBJECT_HUB_LLM_CHAT_PATH", "/chat/completions") or "/chat/completions"
    thinking = pick("SUBJECT_HUB_LLM_ENABLE_THINKING", "0").lower()
    effort = pick("SUBJECT_HUB_LLM_REASONING_EFFORT", "none").lower()
    if effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        effort = "none"
    enabled = thinking in {"1", "true", "on", "yes"}
    return {
        "base_url": pick("SUBJECT_HUB_LLM_BASE_URL"),
        "api_key": pick("SUBJECT_HUB_LLM_API_KEY"),
        "model": pick("SUBJECT_HUB_LLM_MODEL"),
        "chat_path": path,
        "enable_thinking": "1" if enabled else "0",
        "reasoning_effort": "" if enabled and effort == "none" else (effort if enabled else "none"),
    }


def llm_from_env() -> bool:
    return bool(
        os.environ.get("SUBJECT_HUB_LLM_BASE_URL", "").strip()
        or os.environ.get("SUBJECT_HUB_LLM_MODEL", "").strip()
    )


def save_llm_file(
    base_url: str,
    model: str,
    api_key: str,
    chat_path: str,
    enable_thinking: bool = False,
    reasoning_effort: str = "none",
) -> None:
    ensure_dirs()
    path = (chat_path or "/chat/completions").strip() or "/chat/completions"
    effort = (reasoning_effort or "").strip().lower()
    if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", ""}:
        effort = "none"
    if not enable_thinking:
        effort = "none"
    elif effort == "none":
        effort = ""
    lines = [
        f"SUBJECT_HUB_LLM_BASE_URL={base_url.strip()}",
        f"SUBJECT_HUB_LLM_MODEL={model.strip()}",
        f"SUBJECT_HUB_LLM_CHAT_PATH={path}",
        f"SUBJECT_HUB_LLM_API_KEY={api_key.strip()}",
        f"SUBJECT_HUB_LLM_ENABLE_THINKING={'1' if enable_thinking else '0'}",
        f"SUBJECT_HUB_LLM_REASONING_EFFORT={effort}",
        "",
    ]
    LLM_ENV_PATH.write_text("\n".join(lines), encoding="utf-8")


HOST = os.environ.get("SUBJECT_HUB_HOST", "0.0.0.0")
PORT = int(os.environ.get("SUBJECT_HUB_PORT", "8090"))
ADMIN_HOST = os.environ.get("SUBJECT_HUB_ADMIN_HOST", "127.0.0.1")
ADMIN_PORT = int(os.environ.get("SUBJECT_HUB_ADMIN_PORT", "8091"))
COOKIE_NAME = "subject_hub_session"


def secret_key() -> str:
    env = os.environ.get("SUBJECT_HUB_SECRET")
    if env:
        return env
    ensure_dirs()
    path = DATA_DIR / "secret.txt"
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def llm_configured() -> bool:
    cfg = llm_settings()
    return bool(cfg["base_url"] and cfg["model"])
