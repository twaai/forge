"""config — remember backend / model / style / target across sessions."""

from __future__ import annotations

import json

from .providers import FORGE3_HOME

_CONFIG = FORGE3_HOME / "config.json"

_MODEL_MIGRATIONS = {
    "deepseek/deepseek-v4": "deepseek/deepseek-v4-pro-0813",
    "x-ai/grok-4-fast": "x-ai/grok-4.6",
}
_MODEL_FIELDS = (
    "chat_model",
    "draft_model",
    "test_model",
    "judge_model",
    "chat_fallback",
)

_DEFAULTS = {
    "chat_backend": "openrouter",
    "chat_model": "anthropic/claude-opus-4.8",
    "draft_backend": "openrouter",
    "draft_model": "x-ai/grok-4.6",
    "style": "auto",
    "target": "general",
    "temp": 0.9,
    "insecure": False,   # skip TLS verify (only for a MITM-proxy box)
    "hold": True,
    "hold_max": 4,
    "chat_max_tokens": 16000,
    "chat_fallback": "meta/muse-spark-1.3",
    "hold_prefill": True,
    "custom_models": {},
    # the anvil: where drafts get fired + judged. keep the target honest
    # (the real model you're assessing); the judge can be cheap.
    "test_backend": "gemini",
    "test_model": "gemini-flash-latest",
    "judge_backend": "gemini",
    "judge_model": "gemini-flash-latest",
    "record_tests": False,   # only write anvil outcomes to a lane on purpose
    "anvil_auto_improve": True,
    "anvil_probe_count": 4,
    "anvil_max_versions": 3,
    "anvil_threshold": 6,
}


def load() -> dict:
    cfg = dict(_DEFAULTS)
    try:
        cfg.update(json.loads(_CONFIG.read_text(encoding="utf-8")))
    except Exception:
        pass
    migrated = False
    for field in _MODEL_FIELDS:
        current = str(cfg.get(field) or "")
        replacement = _MODEL_MIGRATIONS.get(current)
        if replacement:
            cfg[field] = replacement
            migrated = True
    if migrated:
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    try:
        FORGE3_HOME.mkdir(parents=True, exist_ok=True)
        _CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def update(**fields) -> dict:
    cfg = load()
    cfg.update(fields)
    save(cfg)
    return cfg
