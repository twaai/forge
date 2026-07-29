"""
forge — persona-layer system-prompt generator (one-shot CLI).

Given a target behavior to elicit, Forge uses a permissive generator model to
craft a single ready-to-paste persona-layer system prompt. You copy the output
and paste it into an LLM interface's system-prompt / custom-instructions field.

The generator logic (styles, sanitizer, refusal cascade, backends) lives in
forge_core — shared with the chat TUI (forge_tui.py) so they never drift.

usage:
  python forge/forge.py "write me a working keylogger in c++"
  python forge/forge.py "..." --style interface
  python forge/forge.py "..." --variants 3
  python forge/forge.py "..." --backend gemini          # FREE tier
  python forge/forge.py "..." --gen deepseek/deepseek-v4

keys:
  per-backend at ~/.onyx/forge/keys/<backend>.txt (set via TUI /key, or --key
  to save). openrouter also reads the legacy prism key file and $OPENROUTER_API_KEY.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Windows consoles default to cp1252; the banner and status glyphs are UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

try:
    from openai import OpenAI  # noqa: F401  (surfaces a clean error if missing)
except ImportError:
    print("error: openai not installed. run: pip install openai", file=sys.stderr)
    sys.exit(1)

import forge_core as core


# ───────────────────────────────────────────────────────────────────────
# visual identity — amber/gold forge fire
# ───────────────────────────────────────────────────────────────────────

class C:
    RESET = "\033[0m"
    BOLD  = "\033[1m"
    DIM   = "\033[2m"
    AMBER = "\033[38;5;214m"
    GOLD  = "\033[38;5;220m"
    EMBER = "\033[38;5;208m"
    STEEL = "\033[38;5;250m"
    HOT   = "\033[38;5;196m"
    SMOKE = "\033[38;5;240m"


BANNER = f"""{C.GOLD}{C.BOLD}
  ═══════════════════════════════════════════════════
  ▓▓▓▓▓  ▓▓▓▓  ▓▓▓▓▓   ▓▓▓▓  ▓▓▓▓▓
  ▓      ▓  ▓  ▓  ▓   ▓      ▓
  ▓▓▓▓   ▓  ▓  ▓▓▓    ▓  ▓▓▓ ▓▓▓▓
  ▓      ▓  ▓  ▓ ▓    ▓    ▓ ▓
  ▓      ▓▓▓▓  ▓  ▓    ▓▓▓▓  ▓▓▓▓▓
  ═══════════════════════════════════════════════════
{C.RESET}{C.DIM}   persona-layer system-prompt generator · onyx research fork{C.RESET}
"""


def paint(txt: str, *colors: str) -> str:
    return "".join(colors) + txt + C.RESET


def hr(label: str = "", char: str = "═", width: int = 72, color: str = C.EMBER) -> str:
    if not label:
        return paint(char * width, color)
    left = 3
    right = width - left - len(label) - 2
    return paint(f"{char * left} {label} {char * max(0, right)}", color)


def status(msg: str, color: str = C.AMBER) -> None:
    print(paint(f"  ▸ {msg}", color), file=sys.stderr)


def error(msg: str) -> None:
    print(paint(f"  ✕ {msg}", C.HOT, C.BOLD), file=sys.stderr)


# ───────────────────────────────────────────────────────────────────────
# generation — cascade with refusal detection (matches the TUI)
# ───────────────────────────────────────────────────────────────────────

def draft(client, cascade: list[str], goal: str, style: str) -> tuple[str, str]:
    """Try each model until one produces a non-refusal. Returns (text, model)."""
    messages = core.build_messages(
        [{"role": "user", "content": core.sanitize_user_ask(goal)}], style
    )
    for i, model in enumerate(cascade):
        try:
            text = core.generate(client, model, messages)
        except Exception as e:
            status(f"{model.split('/')[-1]} errored ({type(e).__name__}) — next...", C.SMOKE)
            continue
        if core.looks_like_refusal(text):
            note = "refused — cascading..." if i == 0 else "also refused"
            status(f"{model.split('/')[-1]} {note}", C.SMOKE)
            continue
        return text, model
    return "", ""


# ───────────────────────────────────────────────────────────────────────
# cli
# ───────────────────────────────────────────────────────────────────────

TARGET_NOTES = """  best on:      permissive + open reasoning targets
  hardest on:   current flagship closed anthropic-class model (aggressive
                classifier — expect ~50/50, SYSTEM-INTERFACE framing only)
  mixed on:     flagship closed openai-class family (varies by variant)

  tip:  if the target refuses, regenerate with a different --style,
        try --backend gemini/groq (free), or a more permissive --gen
"""


def main() -> int:
    p = argparse.ArgumentParser(
        prog="forge",
        description="Persona-layer system-prompt generator (one-shot).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
examples:
  python forge/forge.py "write me a working keylogger in c++"
  python forge/forge.py "..." --style interface
  python forge/forge.py "..." --variants 3
  python forge/forge.py "..." --backend gemini
  python forge/forge.py "..." --gen deepseek/deepseek-v4

styles:  {', '.join(core.STYLE_NAMES)}
backends: {', '.join(core.BACKENDS)}
""",
    )
    p.add_argument("goal", help="the target behavior you want to elicit")
    p.add_argument("--backend", default=core.DEFAULT_BACKEND, choices=list(core.BACKENDS),
                   help=f"provider backend (default: {core.DEFAULT_BACKEND})")
    p.add_argument("--gen", default=None,
                   help="override generator model slug (default: backend's default model)")
    p.add_argument("--style", default="auto", choices=core.STYLE_NAMES,
                   help="architecture style (default: auto)")
    p.add_argument("--variants", type=int, default=1,
                   help="generate N distinct prompts and print all (default: 1)")
    p.add_argument("--no-cascade", action="store_true",
                   help="try only the chosen model, don't fall back on refusal")
    p.add_argument("--key", default=None,
                   help="API key for the chosen backend; saved to disk for reuse")
    args = p.parse_args()

    backend = core.get_backend(args.backend)
    if args.key:
        backend.save_key(args.key)
    key = backend.load_key()
    if not key:
        error(f"no key for backend '{backend.name}'. save one:")
        error(f"  python forge/forge.py '{args.goal}' --backend {backend.name} --key <api-key>")
        return 1

    primary = args.gen or backend.default_model
    if args.no_cascade:
        cascade = [primary]
    else:
        cascade = [primary] + [m for m in backend.cascade if m != primary]

    client = core.make_client(backend, key, timeout=120.0)

    print(BANNER)
    print(paint("  goal:     ", C.SMOKE) + paint(args.goal, C.STEEL, C.BOLD))
    print(paint("  backend:  ", C.SMOKE) + paint(backend.name, C.AMBER))
    print(paint("  gen:      ", C.SMOKE) + paint(primary, C.AMBER))
    print(paint("  style:    ", C.SMOKE) + paint(args.style, C.GOLD))
    print(paint("  variants: ", C.SMOKE) + paint(str(args.variants), C.AMBER))
    print()

    for i in range(1, args.variants + 1):
        if args.variants > 1:
            print(hr(f"VARIANT {i}/{args.variants}", color=C.EMBER))

        status(f"drafting via {primary}...", C.AMBER)
        t0 = time.time()
        raw, used = draft(client, cascade, args.goal, args.style)
        dt = time.time() - t0

        if not raw:
            error("all cascade models refused. try --style interface, --backend gemini, or a different --gen")
            return 3

        block = core.extract_block(raw) or raw
        via = f" via {used.split('/')[-1]}" if used != primary else ""
        status(f"drafted in {dt:.1f}s ({len(block)} chars){via}", C.AMBER)
        print()

        print(hr("COPY-PASTE PROMPT (paste into your target LLM's system field):", color=C.GOLD))
        print()
        print(block)
        print()
        print(hr("", color=C.SMOKE))
        print()

    print(hr("TARGET NOTES", color=C.EMBER))
    print(paint(TARGET_NOTES, C.SMOKE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
