"""
providers — one endpoint layer for chat, drafting, and target-testing.

Merges FORGE 3.0's provider wrappers (native Anthropic with prompt caching + usage
cost, reasoning-token handling) with Forge's backend registry (many named
OpenAI-compatible endpoints, per-backend key files, model catalogs, cascade).

The whole engine talks to two things:

  Backend  — a static descriptor: name, dialect, base_url, models, key sources.
  Client   — a live connection with a uniform surface, regardless of SDK:
               stream(model, system, messages)  -> yields text
               complete(model, system, messages) -> str
               list_models() / last_usage()

Two dialects sit behind Client: `anthropic` (native SDK — real Opus-class
classifier behavior, ephemeral cache, token usage) and `openai` (the
chat-completions dialect every other provider speaks). Callers never branch on
which; open_client() returns the right one.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from forge3.core.codex_client import CODEX_MODELS
from forge3.core.model_catalogs import (
    OPENROUTER_MODELS,
    ORCAROUTER_MODELS,
    UNCENSORED_MODELS_BY_BACKEND,
    VENICE_MODELS,
    is_media_only_model,
)

# ───────────────────────────────────────────────────────────────────────
# FORGE 3.0 owns one application directory for keys, config, memory, and vaults.
# ───────────────────────────────────────────────────────────────────────

FORGE3_HOME = Path(os.environ.get("FORGE3_DIR", str(Path.home() / ".forge-3")))
FORGE3_ROOT = FORGE3_HOME
KEYS_DIRS = [FORGE3_HOME / "keys"]
_LEGACY_OR = [FORGE3_HOME / "openrouter_key.txt"]
# OpenRouter (and similar) reserve max output *before* generation. A 65,536
# ceiling at GPT-6 Astra's $50/1M output is $3.28; Claude Fable 5.1 at $25/1M
# is $1.64. Cap every model so worst-case output stays at this budget.
CREDIT_SAFE_OUTPUT_USD = 0.80
MIN_COMPLETION_TOKENS = 256
ASTRA_MAX_COMPLETION_TOKENS = 16_000


# ───────────────────────────────────────────────────────────────────────
# pricing — per 1M tokens (input, output, cached_input). longest match wins.
# carried over from FORGE 3.0 so the tester/chat can report real spend.
# ───────────────────────────────────────────────────────────────────────

PRICING: dict[str, tuple[float, float, float]] = {
    "gpt-6-astra": (10.0, 50.0, 1.0),
    "openai/gpt-5.5-pro": (30.0, 180.0, 3.0),
    "openai/gpt-5.4-pro": (30.0, 180.0, 3.0),
    "openai/gpt-5.2-pro": (21.0, 168.0, 2.1),
    "openai/gpt-5-pro": (15.0, 120.0, 1.5),
    "openai/gpt-5.5": (5.0, 30.0, 0.5),
    "gpt-5.5-pro": (30.0, 180.0, 3.0),
    "gpt-5.4-pro": (30.0, 180.0, 3.0),
    "gpt-5.2-pro": (21.0, 168.0, 2.1),
    "gpt-5-pro": (15.0, 120.0, 1.5),
    "gpt-5.5": (5.0, 30.0, 0.5),
    "claude-fable-5.1": (10.0, 50.0, 1.0),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "deepseek/deepseek-v4-pro-0813": (0.57948, 1.73844, 0.018438),
    "deepseek/deepseek-v4-pro": (0.87, 1.74, 0.0725),
    "deepseek/deepseek-v4-flash-0731": (0.065, 0.18, 0.016),
    "deepseek/deepseek-v4-flash-latest": (0.065, 0.18, 0.016),
    "deepseek/deepseek-v4-flash": (0.07, 0.14, 0.014),
    "venice-uncensored-1-2": (0.2, 0.9, 0.0),
    "glm-5.1": (1.4, 4.4, 0.26),
    "glm-5": (1.0, 3.2, 0.2),
    "glm-4.7": (0.6, 2.2, 0.11),
    "glm-4.6": (0.6, 2.2, 0.11),
    "x-ai/grok-4.6": (2.0, 6.0, 0.5),
    "grok-4.6": (2.0, 6.0, 0.5),
    "google/gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "meta/muse-spark": (1.25, 4.25, 0.15),
    "claude-opus": (15.0, 75.0, 1.5),
    "claude-sonnet": (3.0, 15.0, 0.3),
    "claude-haiku": (0.8, 4.0, 0.08),
    "claude-fable": (10.0, 50.0, 1.0),
    "anthropic/claude-opus": (15.0, 75.0, 1.5),
    "anthropic/claude-sonnet": (3.0, 15.0, 0.3),
    "anthropic/claude-haiku": (0.8, 4.0, 0.08),
    "anthropic/claude-fable-5.1": (10.0, 50.0, 1.0),
    "anthropic/claude-fable-5": (10.0, 50.0, 1.0),
    "anthropic/claude-fable": (10.0, 50.0, 1.0),
    "gpt-5": (5.0, 20.0, 0.5),
    "gpt-4o-mini": (0.15, 0.6, 0.075),
    "gpt-4o": (2.5, 10.0, 1.25),
    "openai/gpt-5": (5.0, 20.0, 0.5),
    "openai/gpt-4o": (2.5, 10.0, 1.25),
    "google/gemini": (0.5, 2.0, 0.125),
    "gemini": (0.5, 2.0, 0.125),
    "deepseek": (0.14, 0.28, 0.028),
    "x-ai/grok": (5.0, 15.0, 0.5),
    "grok": (5.0, 15.0, 0.5),
    "meta-llama": (0.4, 0.6, 0.08),
    "llama": (0.4, 0.6, 0.08),
    "qwen": (0.3, 1.2, 0.06),
    "mistral": (2.0, 6.0, 0.4),
    "moonshotai": (0.5, 2.5, 0.1),
    "kimi": (0.5, 2.5, 0.1),
}
_FALLBACK_PRICE = (3.0, 15.0, 0.3)


def price_for(model: str) -> tuple[float, float, float]:
    m = (model or "").lower()
    matches = [(k, v) for k, v in PRICING.items() if k in m]
    if not matches:
        return _FALLBACK_PRICE
    matches.sort(key=lambda kv: len(kv[0]), reverse=True)
    return matches[0][1]


def credit_safe_completion_tokens(model: str, requested: int) -> int:
    """Clamp completion tokens so reserved output cost cannot exceed the budget."""
    requested = max(1, int(requested or 0))
    price_out = float(price_for(model)[1] or 0.0)
    if price_out <= 0:
        return requested
    affordable = max(
        MIN_COMPLETION_TOKENS,
        int(CREDIT_SAFE_OUTPUT_USD * 1_000_000 / price_out),
    )
    return min(requested, affordable)


# Hidden reasoning and visible text are billed from the SAME completion budget.
# Left unbounded a thinking model can spend the whole credit-safe cap on thinking
# and return an empty bubble — confirmed live on claude-fable-5.1, which burned
# all 16,000 tokens on reasoning and emitted zero content. Reserve a visible
# floor so there is always room to answer.
# Kept separate from hold._THINKING_MODEL_MARKERS on purpose: that list guards
# prefill safety, this one shapes the request. Do not import hold here.
THINKING_MODEL_MARKERS = (
    "claude", "gpt-6-astra", "deepseek-v4", "deepseek-reasoner",
    "grok-4.6", "gemini-3.8", "gemini-3.6", "muse-spark",
    "qwen3.7", "glm-5", "reasoner", "thinking",
)
REASONING_BUDGET_RATIO = 0.5
MIN_REASONING_TOKENS = 1024  # Anthropic rejects a smaller thinking budget
MIN_VISIBLE_TOKENS = 1024


def is_thinking_model(model: str) -> bool:
    """True when a model spends completion tokens on hidden reasoning."""
    key = str(model or "").casefold()
    return any(marker in key for marker in THINKING_MODEL_MARKERS)


def reasoning_budget_for(model: str, completion_tokens: int) -> Optional[int]:
    """Cap hidden reasoning so visible content keeps a floor of the same budget.

    None  — not a thinking model; send no reasoning control at all.
    0     — budget too small to split; ask the provider to skip thinking.
    other — tokens the model may spend thinking, leaving the rest to answer with.
    """
    if not is_thinking_model(model):
        return None
    completion_tokens = max(1, int(completion_tokens or 0))
    if completion_tokens < MIN_REASONING_TOKENS + MIN_VISIBLE_TOKENS:
        return 0
    budget = int(completion_tokens * REASONING_BUDGET_RATIO)
    return max(MIN_REASONING_TOKENS, min(budget, completion_tokens - MIN_VISIBLE_TOKENS))


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cached_input: int = 0) -> float:
    p_in, p_out, p_cache = price_for(model)
    non_cached = max(0, int(input_tokens or 0) - int(cached_input or 0))
    return (non_cached / 1e6) * p_in + (int(cached_input or 0) / 1e6) * p_cache + (int(output_tokens or 0) / 1e6) * p_out


def format_tokens(count: int) -> str:
    count = max(0, int(count or 0))
    if count >= 1000:
        return f"{count / 1000:.0f}k" if count % 1000 == 0 else f"{count / 1000:.1f}k"
    return str(count)


def format_usd(amount: float) -> str:
    value = max(0.0, float(amount or 0.0))
    if value < 0.0005:
        return "free"
    if value < 0.01:
        return f"${value:.3f}"
    return f"${value:.2f}"


def _cost_label(amount: float, backend_name: str) -> str:
    backend = BACKENDS.get(backend_name)
    if backend and backend.free:
        return "free"
    return format_usd(amount)


def typical_jobs(cfg: dict | None = None) -> dict[str, dict]:
    """Ballpark token shapes for a full FORGE 3.0 chat, one Forge draft, one Anvil run."""
    cfg = cfg or {}
    probes = max(2, min(6, int(cfg.get("anvil_probe_count", 4) or 4)))
    versions = max(1, min(3, int(cfg.get("anvil_max_versions", 3) or 3)))
    auto = bool(cfg.get("anvil_auto_improve", True))
    target_in = probes * versions * 4500
    target_out = probes * versions * 2200
    return {
        "assistant": {
            "input": 24000,
            "output": 10000,
            "label": "full chat · ~12 turns",
        },
        "forge": {
            "input": 5000,
            "output": 6000,
            "label": "one system prompt",
        },
        "anvil": {
            "input": target_in,
            "output": target_out,
            "label": f"{probes} probes × {versions} versions · target",
            "probes": probes,
            "versions": versions,
            "auto_improve": auto,
            "judge_input": versions * (4000 + probes * 2500) + 3000,
            "judge_output": versions * 1800 + 800,
            "revise_input": (versions - 1) * 8000 if auto and versions > 1 else 0,
            "revise_output": (versions - 1) * 6000 if auto and versions > 1 else 0,
        },
    }


def _blend_cost(parts: list[dict]) -> str:
    paid_sum = 0.0
    free_names: list[str] = []
    for part in parts:
        if part["cost_label"] == "free":
            free_names.append(part["name"])
        else:
            paid_sum += float(part["cost"])
    if paid_sum <= 0:
        return "free"
    label = format_usd(paid_sum)
    if free_names:
        label += " + " + "/".join(free_names) + " free"
    return label


def _leg(model: str, backend: str, input_tokens: int, output_tokens: int, name: str) -> dict:
    cost = estimate_cost(model, input_tokens, output_tokens)
    return {
        "name": name,
        "backend": backend,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
        "cost_label": _cost_label(cost, backend),
        "use": f"{format_tokens(input_tokens)} in / {format_tokens(output_tokens)} out",
    }


def room_estimates(cfg: dict | None = None) -> dict[str, dict]:
    """Pinned-model estimates for the palette: use + spend per room job."""
    cfg = cfg or {}
    jobs = typical_jobs(cfg)
    assistant = _leg(
        str(cfg.get("chat_model") or ""),
        str(cfg.get("chat_backend") or ""),
        jobs["assistant"]["input"],
        jobs["assistant"]["output"],
        "assistant",
    )
    assistant["label"] = jobs["assistant"]["label"]
    forge = _leg(
        str(cfg.get("draft_model") or ""),
        str(cfg.get("draft_backend") or ""),
        jobs["forge"]["input"],
        jobs["forge"]["output"],
        "forge",
    )
    forge["label"] = jobs["forge"]["label"]
    anvil_job = jobs["anvil"]
    target = _leg(
        str(cfg.get("test_model") or ""),
        str(cfg.get("test_backend") or ""),
        anvil_job["input"],
        anvil_job["output"],
        "target",
    )
    judge = _leg(
        str(cfg.get("judge_model") or ""),
        str(cfg.get("judge_backend") or "gemini"),
        anvil_job["judge_input"],
        anvil_job["judge_output"],
        "judge",
    )
    parts = [target, judge]
    total_in = target["input_tokens"] + judge["input_tokens"]
    total_out = target["output_tokens"] + judge["output_tokens"]
    total_cost = target["cost"] + judge["cost"]
    if anvil_job["revise_input"]:
        revise = _leg(
            str(cfg.get("draft_model") or ""),
            str(cfg.get("draft_backend") or ""),
            anvil_job["revise_input"],
            anvil_job["revise_output"],
            "revise",
        )
        parts.append(revise)
        total_in += revise["input_tokens"]
        total_out += revise["output_tokens"]
        total_cost += revise["cost"]
    anvil = {
        "name": "anvil",
        "backend": target["backend"],
        "model": f"{(target['model'] or 'target').split('/')[-1]} + {(judge['model'] or 'judge').split('/')[-1]}",
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost": total_cost,
        "cost_label": _blend_cost(parts),
        "use": f"{format_tokens(total_in)} in / {format_tokens(total_out)} out",
        "label": anvil_job["label"].replace(" · target", " · target + judge"),
        "parts": parts,
    }
    if anvil_job["auto_improve"] and anvil_job["revise_input"]:
        anvil["label"] += " + revise"
    return {"assistant": assistant, "forge": forge, "anvil": anvil}


# ───────────────────────────────────────────────────────────────────────
# backend descriptor
# ───────────────────────────────────────────────────────────────────────

@dataclass
class Backend:
    name: str
    base_url: str                 # ignored for the anthropic-native dialect
    default_model: str
    dialect: str = "openai"       # "openai" | "anthropic"
    cascade: list[str] = field(default_factory=list)      # tried on refusal/error
    models: list[str] = field(default_factory=list)       # picker catalog
    env_keys: list[str] = field(default_factory=list)     # env vars to check
    request_body: dict[str, object] = field(default_factory=dict)
    free: bool = False
    local: bool = False
    blurb: str = ""

    def __post_init__(self) -> None:
        if not self.cascade:
            self.cascade = [self.default_model]
        if not self.models:
            self.models = list(self.cascade)

    @property
    def tag(self) -> str:
        return "free" if self.free else ("local" if self.local else "paid")

    # ── key resolution: forge3 keys → forge keys → legacy → env ──
    def load_key(self) -> Optional[str]:
        if self.local:
            return "local"
        if self.dialect == "codex":
            from forge3.core.codex_auth import available
            return "codex-login" if available() else None
        for d in KEYS_DIRS:
            f = d / f"{self.name}.txt"
            if f.is_file():
                k = f.read_text(encoding="utf-8").strip()
                if k:
                    return k
        if self.name == "openrouter":
            for f in _LEGACY_OR:
                if f.is_file():
                    k = f.read_text(encoding="utf-8").strip()
                    if k:
                        return k
        for ev in self.env_keys:
            v = os.getenv(ev)
            if v and "paste-your-key" not in v:
                return v.strip()
        return None

    def save_key(self, k: str) -> None:
        if self.dialect == "codex":
            raise ValueError("Codex uses `codex login` on this machine, not a pasted key")
        secret = k.strip()
        if not secret:
            raise ValueError("key is empty")
        d = KEYS_DIRS[0]
        d.mkdir(parents=True, exist_ok=True)
        target = d / f"{self.name}.txt"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=d,
                prefix=f".{self.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(secret)
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            temporary.chmod(0o600)
            os.replace(temporary, target)
            target.chmod(0o600)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def delete_key(self) -> None:
        if self.dialect == "codex":
            raise ValueError("log out with `codex logout`, not Remove")
        (KEYS_DIRS[0] / f"{self.name}.txt").unlink(missing_ok=True)

    def has_key(self) -> bool:
        return self.load_key() is not None


# ───────────────────────────────────────────────────────────────────────
# curated model catalogs (from FORGE 3.0 providers.py, current slugs)
# ───────────────────────────────────────────────────────────────────────

ANTHROPIC_MODELS = [
    "claude-fable-5", "claude-opus-5", "claude-sonnet-5",
    "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5",
]
GEMINI_MODELS = [
    "gemini-3.8-flash", "gemini-3-pro-preview", "gemini-pro-latest", "gemini-3.6-flash",
    "gemini-flash-latest", "gemini-2.5-pro",
]
ZAI_MODELS = [
    "glm-5.3", "glm-5.1", "glm-5", "glm-4.7", "glm-4.6",
]
# ───────────────────────────────────────────────────────────────────────
# the registry
# ───────────────────────────────────────────────────────────────────────

BACKENDS: dict[str, Backend] = {
    "anthropic": Backend(
        "anthropic", "", "claude-opus-4-8", dialect="anthropic",
        cascade=["claude-opus-4-8", "claude-sonnet-5"],
        models=ANTHROPIC_MODELS, env_keys=["ANTHROPIC_API_KEY"],
        blurb="native · Claude direct · real classifier + cache · TEST TARGET",
    ),
    "openrouter": Backend(
        "openrouter", "https://openrouter.ai/api/v1", "x-ai/grok-4.5",
        cascade=["x-ai/grok-4.5", "deepseek/deepseek-v4-pro-0813", "moonshotai/kimi-k3",
                 "nousresearch/hermes-4-405b"],
        models=OPENROUTER_MODELS, env_keys=["OPENROUTER_API_KEY"],
        blurb="paid · every model · strongest drafters + Claude targets",
    ),
    "orcarouter": Backend(
        "orcarouter", "https://api.orcarouter.ai/v1", "orcarouter/auto",
        cascade=["orcarouter/auto", "qwen/qwen3.8-max", "qwen/qwen3.8-27b"],
        models=ORCAROUTER_MODELS,
        env_keys=["ORCAROUTER_API_KEY", "ORCA_API_KEY"],
        blurb="paid · 149 chat models · auto router + flexible FORGE 3.0 models",
    ),
    "zai": Backend(
        "zai", "https://api.z.ai/api/paas/v4/", "glm-5.3",
        cascade=["glm-5.3", "glm-5.1", "glm-4.7"],
        models=ZAI_MODELS, env_keys=["ZAI_API_KEY", "Z_AI_API_KEY"],
        blurb="paid · GLM direct · OpenAI-compatible",
    ),
    "venice": Backend(
        "venice", "https://api.venice.ai/api/v1", "venice-uncensored-1-2",
        cascade=["venice-uncensored-1-2", "qwen-3-8-27b", "qwen-3-6-plus"],
        models=VENICE_MODELS, env_keys=["VENICE_API_KEY"],
        request_body={"venice_parameters": {"include_venice_system_prompt": False}},
        blurb="paid · private models · 10 uncensored picks · FORGE 3.0 prompt authoritative",
    ),
    "gemini": Backend(
        "gemini", "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-flash-latest",
        cascade=["gemini-flash-latest", "gemini-2.5-pro"],
        models=GEMINI_MODELS, env_keys=["GEMINI_API_KEY"], free=True,
        blurb="FREE tier · Gemini · soft target + cheap judge",
    ),
    "groq": Backend(
        "groq", "https://api.groq.com/openai/v1", "deepseek-r1-distill-llama-70b",
        cascade=["deepseek-r1-distill-llama-70b", "moonshotai/kimi-k2-instruct"],
        models=["deepseek-r1-distill-llama-70b", "moonshotai/kimi-k2-instruct", "llama-3.3-70b-versatile"],
        env_keys=["GROQ_API_KEY"], free=True, blurb="FREE · ~500 tok/s",
    ),
    "deepseek": Backend(
        "deepseek", "https://api.deepseek.com", "deepseek-chat",
        cascade=["deepseek-chat", "deepseek-reasoner"],
        models=["deepseek-chat", "deepseek-reasoner"], env_keys=["DEEPSEEK_API_KEY"],
        blurb="$0.14/M in · pennies per prompt",
    ),
    "cerebras": Backend(
        "cerebras", "https://api.cerebras.ai/v1", "qwen-3-235b-a22b-instruct",
        cascade=["qwen-3-235b-a22b-instruct", "llama-3.3-70b"],
        models=["qwen-3-235b-a22b-instruct", "llama-3.3-70b"],
        env_keys=["CEREBRAS_API_KEY"], free=True, blurb="FREE · fastest inference",
    ),
    "xai": Backend(
        "xai", "https://api.x.ai/v1", "grok-4.5", cascade=["grok-4.5"],
        models=["grok-4.6", "grok-4.5", "grok-4"], env_keys=["XAI_API_KEY"], blurb="paid · Grok direct",
    ),
    "openai": Backend(
        "openai", "https://api.openai.com/v1", "gpt-4o",
        cascade=["gpt-4o", "gpt-4o-mini"],
        models=["gpt-6-astra", "gpt-5.6-sol-pro", "gpt-4o", "gpt-4o-mini"],
        env_keys=["OPENAI_API_KEY"], blurb="paid · OpenAI direct",
    ),
    "codex": Backend(
        "codex", "https://chatgpt.com/backend-api/codex", "gpt-5.6-sol",
        dialect="codex",
        cascade=["gpt-5.6-sol", "gpt-5.5"],
        models=list(CODEX_MODELS),
        blurb="your ChatGPT/Codex login · ~/.codex/auth.json",
    ),
    "mistral": Backend(
        "mistral", "https://api.mistral.ai/v1", "mistral-large-latest",
        cascade=["mistral-large-latest"], models=["mistral-large-latest", "open-mistral-nemo"],
        env_keys=["MISTRAL_API_KEY"], blurb="paid · Mistral",
    ),
    "together": Backend(
        "together", "https://api.together.xyz/v1", "deepseek-ai/DeepSeek-R1",
        cascade=["deepseek-ai/DeepSeek-R1"],
        models=["deepseek-ai/DeepSeek-R1", "NousResearch/Hermes-3-Llama-3.1-405B"],
        env_keys=["TOGETHER_API_KEY"], blurb="paid · open models",
    ),
    "local": Backend(
        "local", "http://localhost:1234/v1", "local-model",
        local=True, blurb="offline · LM Studio :1234",
    ),
    "local-ollama": Backend(
        "local-ollama", "http://localhost:11434/v1", "llama3.3",
        local=True, blurb="offline · Ollama :11434",
    ),
}

DEFAULT_BACKEND = "openrouter"


def get_backend(name: str) -> Backend:
    return BACKENDS.get(name, BACKENDS[DEFAULT_BACKEND])


_PROVIDER_LABELS = {
    "openrouter": "OpenRouter",
    "orcarouter": "OrcaRouter",
    "zai": "Z.AI",
    "venice": "Venice",
    "xai": "xAI",
    "openai": "OpenAI",
    "codex": "Codex",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
    "groq": "Groq",
    "deepseek": "DeepSeek",
    "cerebras": "Cerebras",
    "mistral": "Mistral",
    "together": "Together",
}


def _provider_status(error: Exception) -> int | None:
    for owner in (error, getattr(error, "response", None)):
        value = getattr(owner, "status_code", None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    match = re.search(r"(?:error\s+code|status|code)[^0-9]{0,12}([1-5][0-9]{2})", str(error), re.IGNORECASE)
    return int(match.group(1)) if match else None


def format_provider_error(error: Exception, backend_name: str) -> str:
    """Return a concise UI-safe provider failure without raw response JSON."""
    backend_key = str(backend_name or "provider").strip().casefold()
    label = _PROVIDER_LABELS.get(backend_key, backend_key.title() or "Provider")
    raw = " ".join(str(error).split()).casefold()
    status = _provider_status(error)
    key_action = (
        f"Press Ctrl+P, choose {backend_key.upper()}, click it, "
        "and paste a fresh key."
    )
    if backend_key == "codex":
        login_failure = status == 401 or any(token in raw for token in (
            "codex login expired", "no codex login", "run `codex login`",
            "auth.json is corrupt", "missing an account id",
        ))
        if login_failure:
            return "Codex login expired — run `codex login`."
        if status in {400, 404} and any(token in raw for token in (
            "model is not supported", "model not supported",
            "not supported when using codex", "invalid model",
            "unknown model", "model not found",
        )):
            return (
                "Codex does not currently offer the selected model on this "
                "ChatGPT login. Pin another Codex model with Ctrl+M."
            )
        if status == 400:
            return "Codex rejected the request (HTTP 400). Check the selected Codex model and retry."
        if status == 403:
            return "Codex denied this ChatGPT login or model. Check the subscription permissions."
        if status == 429:
            return "Codex rate limit reached. Wait briefly, then retry."
        if status is not None and status >= 500:
            return f"Codex is temporarily unavailable (HTTP {status}). Retry shortly."
    if status == 401:
        reason = "API key expired" if "expired" in raw else "API key was rejected"
        return f"{label} {reason}. {key_action}"
    if status == 402:
        return f"{label} credits are depleted. Add provider credits, then retry."
    if status == 403:
        return f"{label} denied access for this key or model. Check its provider permissions."
    if status == 404 or "model not found" in raw:
        return f"{label} does not currently offer the selected model. Pin another model with Ctrl+M."
    if status == 400:
        if any(token in raw for token in (
            "invalid model", "unknown model", "model not found", "no endpoints",
            "not a valid model", "model id", "does not exist",
        )):
            return f"{label} does not currently offer the selected model. Pin a live model with Ctrl+M."
        if "reasoning_content" in raw or "reasoning content" in raw:
            return (
                f"{label} rejected missing reasoning state. Start a new chat or retry "
                "with the same reasoning model."
            )
        if any(token in raw for token in (
            "unsupported parameter", "unknown parameter", "not supported",
            "temperature", "max_tokens", "max completion tokens",
        )):
            return f"{label} rejected a request parameter for this model. Update the model profile or pin another model."
        return f"{label} rejected the request (HTTP 400). Check the pinned model and its request settings."
    if status == 429:
        return f"{label} rate limit reached. Wait briefly, then retry."
    if status is not None and status >= 500:
        return f"{label} is temporarily unavailable (HTTP {status}). Retry shortly."
    if "timed out" in raw or "timeout" in raw:
        return f"{label} request timed out. Check the connection, then retry."
    if "connection" in raw or "network" in raw:
        return f"{label} connection failed. Check the network, then retry."
    suffix = f" (HTTP {status})" if status is not None else ""
    return f"{label} request failed{suffix}. Check the provider key, model, and connection."


def model_choices(overlays: dict[str, list[str]] | None = None) -> list[dict]:
    """Every backend×model pair, flattened for a picker."""
    out: list[dict] = []
    for name, be in BACKENDS.items():
        keyed = be.has_key()
        extra = overlays.get(name, []) if isinstance(overlays, dict) else []
        catalog = list(dict.fromkeys([*be.models, *extra]))
        # Image and voice models return no chat text, so a pick can only ever
        # paint an empty bubble. Filtered here rather than in the snapshot alone
        # so a live /models refresh or a Ctrl+M paste cannot reintroduce them.
        catalog = [model for model in catalog if not is_media_only_model(model)]
        for model in catalog:
            traits = (
                ["uncensored"]
                if model in UNCENSORED_MODELS_BY_BACKEND.get(name, frozenset())
                else []
            )
            out.append({
                "backend": name, "model": model, "tag": be.tag, "keyed": keyed,
                "is_default": model == be.default_model,
                "label": f"{name} · {model}",
                "traits": traits,
                "search": f"{name} {model} {' '.join(traits)}".lower(),
                "price_in": price_for(model)[0],
                "price_out": price_for(model)[1],
            })
    return out


# ───────────────────────────────────────────────────────────────────────
# clients — uniform surface over two SDK dialects
# ───────────────────────────────────────────────────────────────────────

class Client(ABC):
    def __init__(self) -> None:
        self._last_usage: Optional[dict] = None
        self._last_finish_reason: Optional[str] = None

    @abstractmethod
    def stream(self, model: str, system: Optional[str], messages: list[dict],
               max_tokens: int = 4000, temperature: float = 0.9) -> Iterator[str]: ...

    def complete(self, model: str, system: Optional[str], messages: list[dict],
                 max_tokens: int = 4000, temperature: float = 0.9,
                 json_mode: bool = False) -> str:
        self._last_visible = ""
        self._last_hidden = ""
        try:
            text = "".join(
                self.stream(
                    model, system, messages, max_tokens, temperature, json_mode=json_mode
                )
            ).strip()
        except TypeError:
            text = "".join(
                self.stream(model, system, messages, max_tokens, temperature)
            ).strip()
        hidden = str(getattr(self, "_hidden_text", "") or "").strip()
        self._last_visible = text
        self._last_hidden = hidden
        # Visible first for chat. JSON recovery also reads _last_hidden.
        return text or hidden

    def list_models(self) -> list[str]:
        return []

    def last_usage(self) -> Optional[dict]:
        return self._last_usage

    def last_finish_reason(self) -> Optional[str]:
        return self._last_finish_reason

    def last_reasoning_content(self) -> str:
        return str(getattr(self, "_hidden_text", "") or "").strip()

    def last_refusal(self) -> str:
        return str(getattr(self, "_last_refusal", "") or "").strip()


class AnthropicClient(Client):
    """Native Claude — the real target surface. Ephemeral cache on system, usage."""

    def __init__(self, key: str, verify: bool = True) -> None:
        super().__init__()
        from anthropic import Anthropic
        kwargs = {}
        if not verify:  # only for the MITM-proxy box; see providers note
            import httpx
            kwargs["http_client"] = httpx.Client(verify=False, timeout=180.0)
        self.client = Anthropic(api_key=key, **kwargs)

    def stream(self, model, system, messages, max_tokens=4000, temperature=0.9,
               json_mode=False):
        self._last_usage = None
        self._last_finish_reason = None
        sys_block = ([{"type": "text", "text": system,
                       "cache_control": {"type": "ephemeral"}}] if system else None)
        portable_messages = [
            {"role": message["role"], "content": message.get("content", "")}
            for message in messages
        ]
        with self.client.messages.stream(
            model=model,
            max_tokens=credit_safe_completion_tokens(model, max_tokens),
            temperature=temperature,
            system=sys_block, messages=portable_messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
            try:
                final = stream.get_final_message()
                self._last_finish_reason = getattr(final, "stop_reason", None)
                u = getattr(final, "usage", None)
                if u:
                    self._last_usage = {
                        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
                        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
                        "cache_read_input_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
                    }
            except Exception:
                pass

    def list_models(self):
        return list(ANTHROPIC_MODELS)


class OpenAICompatClient(Client):
    """Every other provider. Keeps hidden reasoning separate from visible text."""

    _EXTRA = {"HTTP-Referer": "https://localhost/forge3", "X-Title": "forge3"}

    def __init__(
        self,
        base_url: str,
        key: str,
        verify: bool = True,
        request_body: dict[str, object] | None = None,
    ) -> None:
        super().__init__()
        from openai import OpenAI
        kwargs = {}
        if not verify:
            import httpx
            kwargs["http_client"] = httpx.Client(verify=False, timeout=180.0)
        self._base_url = base_url
        self._request_body = dict(request_body or {})
        self.client = OpenAI(base_url=base_url, api_key=key, **kwargs)

    def _gemini_endpoint(self, model: str) -> bool:
        blob = f"{getattr(self, '_base_url', '')} {model}".lower()
        return "gemini" in blob or "generativelanguage" in blob

    @staticmethod
    def _model_leaf(model: str) -> str:
        return str(model or "").rsplit("/", 1)[-1].casefold()

    @staticmethod
    def _astra_model(model: str) -> bool:
        return OpenAICompatClient._model_leaf(model).startswith("gpt-6-astra")

    @staticmethod
    def _openai_modern_model(model: str) -> bool:
        """Astra, GPT-5*, and o-series need developer + max_completion_tokens."""
        leaf = OpenAICompatClient._model_leaf(model).split(":", 1)[0]
        return (
            OpenAICompatClient._astra_model(model)
            or leaf.startswith("gpt-5")
            or leaf.startswith(("o1", "o3", "o4"))
        )

    @staticmethod
    def _fable_model(model: str) -> bool:
        return OpenAICompatClient._model_leaf(model).startswith("claude-fable")

    def _developer_instruction_model(self, model: str) -> bool:
        # Same Chat Completions shape that made Astra answer in FORGE 3.0:
        # developer instruction, max_completion_tokens, no temperature.
        # Model-leaf match, so OpenAI direct, OpenRouter, and OrcaRouter all get it.
        return self._openai_modern_model(model)

    def _msgs(self, system, messages, model="", role=None):
        if role is None:
            role = (
                "developer" if self._developer_instruction_model(model) else "system"
            )
        prepared = []
        for message in messages:
            item = {
                "role": message.get("role", "user"),
                "content": message.get("content", ""),
            }
            reasoning = message.get("reasoning_content")
            reasoning_model = str(message.get("reasoning_model") or "")
            if reasoning and (not reasoning_model or reasoning_model == model):
                item["reasoning_content"] = reasoning
            prepared.append(item)
        return ([{"role": role, "content": system}] if system else []) + prepared

    def stream(self, model, system, messages, max_tokens=4000, temperature=0.9,
               json_mode=False):
        self._last_usage = None
        self._last_finish_reason = None
        self._hidden_text = ""
        self._last_refusal = ""
        hidden: list[str] = []
        developer_instruction = self._developer_instruction_model(model)
        completion_tokens = credit_safe_completion_tokens(model, max_tokens)
        create_kwargs = {
            "model": model,
            "messages": self._msgs(system, messages, model),
            "stream": True,
            "stream_options": {"include_usage": True},
            "extra_headers": self._EXTRA,
        }
        if developer_instruction:
            create_kwargs["max_completion_tokens"] = completion_tokens
        else:
            create_kwargs["max_tokens"] = completion_tokens
            create_kwargs["temperature"] = temperature
        provider_body = dict(getattr(self, "_request_body", {}))
        extra_body = dict(provider_body)
        gemini_endpoint = self._gemini_endpoint(model)
        if json_mode:
            create_kwargs["response_format"] = {"type": "json_object"}
            # Gemini thinking eats the token budget; JSON never lands in content.
            if gemini_endpoint:
                extra_body["google"] = {"thinking_config": {"thinking_budget": 0}}
        # Bound the thinking half of the completion budget so visible text keeps
        # room. Gemini endpoints have their own control above and do not take it.
        reasoning_budget = None if gemini_endpoint else reasoning_budget_for(
            model, completion_tokens
        )
        if reasoning_budget is not None:
            extra_body["reasoning"] = (
                {"max_tokens": reasoning_budget} if reasoning_budget
                else {"enabled": False}
            )
        if extra_body:
            create_kwargs["extra_body"] = extra_body
        attempts = [dict(create_kwargs)]
        if json_mode:
            if gemini_endpoint:
                portable = dict(create_kwargs)
                if provider_body:
                    portable["extra_body"] = provider_body
                else:
                    portable.pop("extra_body", None)
                attempts.append(portable)
            bare = dict(attempts[-1])
            bare.pop("response_format", None)
            attempts.append(bare)
        if reasoning_budget is not None:
            # Endpoints that reject the unified reasoning field must still answer.
            plain = dict(attempts[-1])
            plain_body = {
                k: v for k, v in dict(plain.get("extra_body", {})).items()
                if k != "reasoning"
            }
            if plain_body:
                plain["extra_body"] = plain_body
            else:
                plain.pop("extra_body", None)
            attempts.append(plain)
        if self._fable_model(model) and developer_instruction:
            # OpenRouter Claude may reject developer / max_completion_tokens.
            # Keep the Astra-shaped first shot; fall back to the old shape.
            classic = dict(attempts[-1])
            classic["messages"] = self._msgs(system, messages, model, role="system")
            classic.pop("max_completion_tokens", None)
            classic["max_tokens"] = completion_tokens
            classic["temperature"] = temperature
            attempts.append(classic)
        stream = None
        last_error: Exception | None = None
        for kwargs in attempts:
            try:
                stream = self.client.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                last_error = exc
        if stream is None:
            raise last_error if last_error else RuntimeError("judge stream failed")
        try:
            for chunk in stream:
                u = getattr(chunk, "usage", None)
                if u:
                    cached = 0
                    d = getattr(u, "prompt_tokens_details", None)
                    if d is not None:
                        cached = int(getattr(d, "cached_tokens", 0) or 0)
                    self._last_usage = {
                        "input_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
                        "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                        "cache_read_input_tokens": cached,
                    }
                if not chunk.choices:
                    continue
                finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                if finish_reason:
                    self._last_finish_reason = str(finish_reason)
                delta = chunk.choices[0].delta
                refused = getattr(delta, "refusal", None)
                if refused:
                    self._last_refusal += str(refused)
                piece = getattr(delta, "content", None)
                if piece:
                    yield piece
                    continue
                for attr in ("reasoning", "reasoning_content"):
                    hidden_piece = getattr(delta, attr, None)
                    if hidden_piece:
                        hidden.append(str(hidden_piece))
                        break
        finally:
            self._hidden_text = "".join(hidden)

    def list_models(self):
        try:
            ids = [m.id for m in self.client.models.list().data]
            return sorted(i[len("models/"):] if i.startswith("models/") else i for i in ids)
        except Exception:
            return []


class CodexClient(Client):
    """ChatGPT/Codex subscription on this machine. Not platform API keys."""

    def __init__(self, verify: bool = True) -> None:
        super().__init__()
        self._verify = verify

    def stream(
        self,
        model,
        system,
        messages,
        max_tokens=4000,
        temperature=0.9,
        json_mode=False,
    ):
        del temperature, json_mode
        from forge3.core.codex_auth import CodexAuthError, session
        from forge3.core.codex_client import (
            CODEX_URL,
            delta_text,
            hidden_text,
            model_leaf,
            to_input,
        )

        self._last_usage = None
        self._last_finish_reason = None
        self._hidden_text = ""
        self._last_refusal = ""
        hidden: list[str] = []
        body = {
            "model": model_leaf(model),
            "instructions": str(system or ""),
            "input": to_input(list(messages or [])),
            "stream": True,
            "store": False,
        }
        # The ChatGPT subscription endpoint rejects max_output_tokens even
        # though the public Responses API accepts it. Subscription usage is
        # not API-credit metered, so omit the unsupported field entirely.
        del max_tokens
        if not body["input"]:
            body["input"] = [{
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": " "}],
            }]
        try:
            yield from self._stream_once(CODEX_URL, body, hidden, session, CodexAuthError, delta_text, hidden_text)
        finally:
            self._hidden_text = "".join(hidden)

    def _stream_once(self, url, body, hidden, session, CodexAuthError, delta_text, hidden_text):
        import httpx
        from forge3.core.codex_client import CodexRequestError, safe_error_detail

        access, account = session()
        headers = {
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "chatgpt-account-id": account,
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
        }
        with httpx.Client(verify=self._verify, timeout=180.0) as client:
            with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code == 401:
                    raise CodexAuthError("Codex login expired — run `codex login`")
                if response.status_code >= 400:
                    detail = safe_error_detail(response.read())
                    suffix = f" {detail}" if detail else ""
                    raise CodexRequestError(
                        f"Codex request failed (HTTP {response.status_code}).{suffix}",
                        response.status_code,
                    )
                for raw in response.iter_lines():
                    line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    kind = str(payload.get("type") or "")
                    if kind in {"response.failed", "error"}:
                        detail = safe_error_detail(payload)
                        suffix = f" {detail}" if detail else ""
                        raise CodexRequestError(f"Codex request failed.{suffix}")
                    piece = delta_text(payload)
                    if piece:
                        yield piece
                    hid = hidden_text(payload)
                    if hid:
                        hidden.append(hid)
                    if kind == "response.completed":
                        usage = None
                        nested = payload.get("response")
                        if isinstance(nested, dict):
                            usage = nested.get("usage")
                        if not isinstance(usage, dict):
                            usage = payload.get("usage")
                        if isinstance(usage, dict):
                            self._last_usage = {
                                "input_tokens": int(usage.get("input_tokens") or 0),
                                "output_tokens": int(usage.get("output_tokens") or 0),
                                "cache_read_input_tokens": int(
                                    usage.get("cache_read_input_tokens") or 0
                                ),
                            }
                        self._last_finish_reason = "stop"

    def list_models(self):
        from forge3.core.codex_client import CODEX_MODELS

        return list(CODEX_MODELS)


def open_client(backend: Backend, key: Optional[str] = None, verify: bool = True) -> Client:
    """Resolve a key (arg → backend sources) and open the right client."""
    if backend.dialect == "codex":
        if not backend.has_key():
            raise RuntimeError("no Codex login on this machine — run `codex login`")
        return CodexClient(verify=verify)
    resolved = key or backend.load_key()
    if not resolved:
        raise RuntimeError(
            f"no key for backend '{backend.name}' — set one "
            f"(~/.forge-3/keys/{backend.name}.txt) or via env {backend.env_keys}"
        )
    if backend.dialect == "anthropic":
        return AnthropicClient(resolved, verify=verify)
    return OpenAICompatClient(
        backend.base_url,
        resolved,
        verify=verify,
        request_body=backend.request_body,
    )
