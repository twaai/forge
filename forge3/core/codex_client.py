"""ChatGPT Codex subscription helpers. The live client lives in providers.py."""

from __future__ import annotations

import json
import re

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_MODELS = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.1-codex",
    "gpt-5.1-codex-mini",
    "gpt-5.1-codex-max",
]


class CodexRequestError(RuntimeError):
    """A UI-classifiable Codex backend failure with no auth material attached."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def safe_error_detail(payload: bytes | str | dict, limit: int = 600) -> str:
    """Extract a bounded backend sentence while redacting credential-shaped text."""
    value: object = payload
    if isinstance(payload, bytes):
        value = payload.decode("utf-8", "replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    if isinstance(value, dict):
        detail = value.get("detail")
        error = value.get("error")
        if isinstance(detail, str):
            text = detail
        elif isinstance(error, dict) and isinstance(error.get("message"), str):
            text = error["message"]
        elif isinstance(error, str):
            text = error
        else:
            text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value or "")
    text = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", text, flags=re.IGNORECASE)
    text = re.sub(
        r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        "<redacted>",
        text,
    )
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<redacted>", text)
    return " ".join(text.split())[: max(1, int(limit))]


def model_leaf(model: str) -> str:
    raw = str(model or "").strip()
    if raw.startswith("openai/"):
        raw = raw[len("openai/") :]
    return raw.split(":", 1)[0]


def to_input(messages: list[dict]) -> list[dict]:
    items: list[dict] = []
    for message in messages:
        role = str(message.get("role") or "user")
        text = str(message.get("content") or "")
        if role in {"system", "developer"}:
            continue
        if role == "assistant":
            items.append({
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            })
        else:
            items.append({
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            })
    return items


def delta_text(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    kind = str(payload.get("type") or "")
    if kind in {"response.output_text.delta", "response.output_text.delta.done"}:
        return str(payload.get("delta") or payload.get("text") or "")
    if "output_text" in kind and isinstance(payload.get("delta"), str):
        return payload["delta"]
    delta = payload.get("delta")
    if isinstance(delta, dict):
        return str(delta.get("text") or "")
    return ""


def hidden_text(payload: dict) -> str:
    kind = str(payload.get("type") or "")
    if "reasoning" in kind and "delta" in kind:
        return str(payload.get("delta") or payload.get("text") or "")
    return ""
