"""Forge 3.0 picker: cheap live slug per family, plus a few flagships that earn it."""

from __future__ import annotations

from typing import Any

from forge3.core import providers as P

DEFAULT_BACKEND = "openrouter"
DEFAULT_MODEL = "x-ai/grok-4-fast"

# Cheap floor + mid Kimi + selected flagships including Grok 4.5 and Kimi K3.
CHEAP_BY_BACKEND: dict[str, tuple[str, ...]] = {
    "openrouter": (
        "x-ai/grok-4-fast",
        "x-ai/grok-4.5",
        "x-ai/grok-4.6",
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro-0813",
        "z-ai/glm-5.3-flash",
        "z-ai/glm-5.3",
        "moonshotai/kimi-k2",
        "moonshotai/kimi-k2.6",
        "moonshotai/kimi-k2.7-code",
        "moonshotai/kimi-k3",
        "minimax/minimax-m3",
        "qwen/qwen3.8-flash",
        "qwen/qwen3.8-max-0902",
        "stepfun/step-3.7-flash",
        "inclusionai/ling-3.0-flash",
        "bytedance-seed/seed-1.6-flash",
        "meituan/longcat-2.0",
        "tencent/hy3",
        "xiaomi/mimo-v2.5",
    ),
    "orcarouter": (
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro-0813",
        "z-ai/glm-5.3-flash",
        "z-ai/glm-5.3",
        "kimi/kimi-k2.5",
        "kimi/kimi-k2.6",
        "kimi/kimi-k2.7-code",
        "kimi/kimi-k3",
        "minimax/minimax-m3",
        "qwen/qwen3.8-flash",
        "qwen/qwen3.8-max",
        "grok/grok-4.5",
        "grok/grok-4.6",
        "tencent/hy3",
    ),
    "zai": ("glm-5.3-flash", "glm-5.3"),
    "deepseek": ("deepseek-chat", "deepseek-reasoner"),
    "groq": ("moonshotai/kimi-k2-instruct",),
    "xai": ("grok-4-fast", "grok-4.5", "grok-4.6"),
}

KEEP_ALL = frozenset({"local", "local-ollama"})

# Slugs missing from the Sept 10 snapshot or from a backend's curated list.
INJECT: tuple[tuple[str, str], ...] = (
    ("openrouter", "x-ai/grok-4-fast"),
    ("xai", "grok-4-fast"),
    ("zai", "glm-5.3-flash"),
)

CHEAP_CASCADE: dict[str, tuple[str, ...]] = {
    "openrouter": (
        "x-ai/grok-4-fast",
        "deepseek/deepseek-v4-flash",
        "z-ai/glm-5.3-flash",
    ),
    "orcarouter": ("qwen/qwen3.8-flash", "deepseek/deepseek-v4-flash"),
    "zai": ("glm-5.3-flash",),
    "deepseek": ("deepseek-chat",),
    "groq": ("moonshotai/kimi-k2-instruct",),
    "xai": ("grok-4-fast",),
}

PIN_REMAP: dict[tuple[str, str], tuple[str, str]] = {
    ("openrouter", "~x-ai/grok-latest"): ("openrouter", "x-ai/grok-4.6"),
    ("xai", "grok-4"): ("xai", "grok-4.5"),
    ("zai", "glm-5.1"): ("zai", "glm-5.3"),
    ("zai", "glm-5"): ("zai", "glm-5.3"),
}


def is_allowed(backend: str, model: str) -> bool:
    if backend in KEEP_ALL:
        return True
    allowed = CHEAP_BY_BACKEND.get(backend)
    return bool(allowed) and model in allowed


def remap_pin(backend: str | None, model: str | None) -> tuple[str, str]:
    backend = str(backend or DEFAULT_BACKEND)
    model = str(model or DEFAULT_MODEL)
    mapped = PIN_REMAP.get((backend, model))
    if mapped:
        return mapped
    if is_allowed(backend, model):
        return backend, model
    return DEFAULT_BACKEND, DEFAULT_MODEL


def cascade_for(backend: str, pinned: str) -> list[str]:
    models = [pinned]
    for alt in CHEAP_CASCADE.get(backend, ()):
        if alt and alt not in models:
            models.append(alt)
        if len(models) >= 3:
            break
    return models


def _row(backend: str, model: str, keyed: bool) -> dict[str, Any]:
    be = P.BACKENDS[backend]
    price = P.price_for(model)
    return {
        "backend": backend,
        "model": model,
        "tag": be.tag,
        "keyed": keyed,
        "is_default": backend == DEFAULT_BACKEND and model == DEFAULT_MODEL,
        "label": f"{backend} · {model}",
        "traits": [],
        "search": f"{backend} {model}".lower(),
        "price_in": price[0],
        "price_out": price[1],
    }


def cheap_choices(overlays: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """v4 catalog, stripped to the cheap families, with missing slugs injected."""
    full = P.model_choices(overlays)
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in full:
        backend, model = row["backend"], row["model"]
        if not is_allowed(backend, model):
            continue
        key = (backend, model)
        if key in seen:
            continue
        seen.add(key)
        row = dict(row)
        row["is_default"] = backend == DEFAULT_BACKEND and model == DEFAULT_MODEL
        out.append(row)
    for backend, model in INJECT:
        if (backend, model) in seen or backend not in P.BACKENDS:
            continue
        keyed = P.BACKENDS[backend].has_key()
        out.append(_row(backend, model, keyed))
        seen.add((backend, model))
    rank: dict[tuple[str, str], int] = {}
    index = 0
    for backend, models in CHEAP_BY_BACKEND.items():
        for model in models:
            rank[(backend, model)] = index
            index += 1
    out.sort(
        key=lambda row: (
            row["backend"] not in CHEAP_BY_BACKEND,
            rank.get((row["backend"], row["model"]), 10_000),
            row["backend"],
            row["model"],
        )
    )
    return out
