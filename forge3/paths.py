"""FORGE 3.0 application storage."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

# FORGE 3.0 keeps a compact model-selection overlay.
OVERLAY_KEYS = (
    "draft_backend",
    "draft_model",
)


def forge_dir() -> Path:
    return Path(os.environ.get("FORGE3_DIR", str(Path.home() / ".forge-3")))


def forge_config() -> Path:
    return forge_dir() / "config.json"


def forge_chats() -> Path:
    return forge_dir() / "chats"


def history_key_path() -> Path:
    return forge_dir() / "history.key"


def history_secret() -> str:
    path = history_key_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(32)
    path.write_text(secret, encoding="utf-8")
    return secret


def drawer_label() -> str:
    folder = forge_dir().expanduser()
    try:
        relative = folder.resolve().relative_to(Path.home().resolve())
        return "~/" + relative.as_posix()
    except ValueError:
        return str(folder)


def load_overlay() -> dict[str, Any]:
    try:
        data = json.loads(forge_config().read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: data[key] for key in OVERLAY_KEYS if key in data}


def save_overlay(cfg: dict[str, Any]) -> None:
    folder = forge_dir()
    folder.mkdir(parents=True, exist_ok=True)
    payload = {key: cfg[key] for key in OVERLAY_KEYS if key in cfg}
    forge_config().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
