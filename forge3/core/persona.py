"""
persona — the FORGE 3.0 chat brain, loaded from the vault.

FORGE 3.0's system prompt is a sealed secret like any other. The chat frontend asks
this module for the assembled system text; it pulls the persona from the
PromptSource and never touches a plaintext file. This is the fix for the current
FORGE 3.0 app's leak (it bundled system_prompt.txt in cleartext).
"""

from __future__ import annotations

from .sealed_prompts import reveal

ANTHROPIC_SPINE_IDENTITY = reveal('ANTHROPIC_SPINE_IDENTITY')
ANTHROPIC_FABLE5_IDENTITY = reveal('ANTHROPIC_FABLE5_IDENTITY')
ANTHROPIC_FABLE5_IDENTITY_STRONG = reveal('ANTHROPIC_FABLE5_IDENTITY_STRONG')
ANTHROPIC_FABLE5_INTERN_IDENTITY = reveal('ANTHROPIC_FABLE5_INTERN_IDENTITY')
ANTHROPIC_BARE_IDENTITY = reveal('ANTHROPIC_BARE_IDENTITY')
ANTHROPIC_COMPACT_IDENTITY = reveal('ANTHROPIC_COMPACT_IDENTITY')


from typing import Optional

from . import vault
from .vault import PromptSource

# Live-proved 13 Sep 2026, OpenRouter, user "hey":
# Fable 5.1 ate this spine (12 Sep). Fable 5 content-filters it.

# Flip to "strong" to restore the 13 Sep strengthen cut (751 + 277 intern, no bare rung).
FABLE5_PROFILE = "quiet"

# Live-proved 13 Sep 2026 on anthropic/claude-fable-5: 520 chars + system → stop.

# Strengthen cut. Kept so FABLE5_PROFILE = "strong" puts the old process back.

# Fable 5 intern on the quiet ladder. Other Claude ids still use COMPACT.

# Last Fable 5 identity on a content-filter turn. No HOLD text on this rung.

# Other Claude first shots, and Fable 5 intern when FABLE5_PROFILE is "strong".


def _leaf(model: str | None) -> str:
    raw = str(model or "").strip().casefold().split(":", 1)[0]
    return raw.rsplit("/", 1)[-1]


def uses_fable_51(model: str | None) -> bool:
    leaf = _leaf(model)
    return "fable" in leaf and "5.1" in leaf


def uses_fable_5(model: str | None) -> bool:
    """Fable 5.0 only — not 5.1. Quiet ladder unless FABLE5_PROFILE is strong."""
    if uses_fable_51(model):
        return False
    leaf = _leaf(model)
    return "fable-5" in leaf or leaf.startswith("claude-fable-5") or leaf.startswith("fable-5")


def uses_fable_51_spine(model: str | None) -> bool:
    """Fable 5.1 takes the longer spine. Fable 5 does not — it content-filters it."""
    return uses_fable_51(model)


def fable5_uses_quiet_ladder() -> bool:
    """Quiet first shot + stripped intern + bare filter rung. Strong is the 751 cut."""
    return str(FABLE5_PROFILE or "").strip().casefold() != "strong"


def fable5_first_identity() -> str:
    if fable5_uses_quiet_ladder():
        return ANTHROPIC_FABLE5_IDENTITY
    return ANTHROPIC_FABLE5_IDENTITY_STRONG


def fable5_intern_identity() -> str:
    if fable5_uses_quiet_ladder():
        return ANTHROPIC_FABLE5_INTERN_IDENTITY
    return ANTHROPIC_COMPACT_IDENTITY


def uses_anthropic_compact(model: str | None, backend: str | None = None) -> bool:
    """Any Claude/Fable slug, on any pipe, takes a compact identity.

    Anthropic content-filters the vault PERSONA. The provider does not matter:
    OpenRouter, OrcaRouter, and native Anthropic all land on the same filter.
    Astra, Grok, and everything else keep the vault brain.
    """
    if str(backend or "").strip().casefold() == "anthropic":
        return True
    raw = str(model or "").strip().casefold().split(":", 1)[0]
    if not raw:
        return False
    leaf = raw.rsplit("/", 1)[-1]
    vendor = raw.rsplit("/", 1)[0] if "/" in raw else ""
    if vendor == "anthropic":
        return True
    return leaf.startswith("claude") or leaf.startswith("fable")


def system_prompt(
    source: PromptSource,
    extra: Optional[str] = None,
    model: str = "",
    compact: bool = False,
    backend: str = "",
    intern: bool = False,
    bare: bool = False,
) -> str:
    """The FORGE 3.0 system prompt from the vault, optionally with appended context
    (session notes, memory index) the chat layer wants folded in."""
    if uses_anthropic_compact(model, backend):
        base = ""
        if not intern and not bare and source.has(vault.PERSONA_ANTHROPIC):
            base = str(source.get(vault.PERSONA_ANTHROPIC) or "").strip()
        if not base:
            if bare and uses_fable_5(model):
                base = ANTHROPIC_BARE_IDENTITY
            elif intern:
                base = (
                    fable5_intern_identity()
                    if uses_fable_5(model)
                    else ANTHROPIC_COMPACT_IDENTITY
                )
            elif uses_fable_5(model):
                base = fable5_first_identity()
            elif uses_fable_51(model):
                base = ANTHROPIC_SPINE_IDENTITY
            else:
                base = ANTHROPIC_COMPACT_IDENTITY
    else:
        base = source.get(vault.PERSONA)
    return f"{base}\n\n{extra}" if extra else base


def build_chat(
    source: PromptSource,
    conversation: list[dict],
    extra: Optional[str] = None,
    model: str = "",
    compact: bool = False,
    backend: str = "",
    intern: bool = False,
    bare: bool = False,
) -> tuple[str, list[dict]]:
    """Return (system, messages) ready for providers.Client.stream/complete.
    System is kept separate (not folded into messages) so the Anthropic dialect
    can cache it as an ephemeral block."""
    return system_prompt(
        source,
        extra,
        model=model,
        compact=compact,
        backend=backend,
        intern=intern,
        bare=bare,
    ), conversation
