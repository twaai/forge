"""
forge — persona-layer system-prompt generator (one-shot CLI).

Given a target behavior to elicit, Forge uses a permissive generator model to
craft a single ready-to-paste persona-layer system prompt. You copy the output
and paste it into an LLM interface's system-prompt / custom-instructions field.

The generator logic (styles, sanitizer, refusal cascade, backends) lives in
forge_core — shared with the chat TUI (forge_tui.py) so they never drift.

usage:
  python forge.py "your goal here"
  python forge.py "..." --style interface
  python forge.py "..." --variants 3
  python forge.py "..." --backend gemini          # FREE tier
  python forge.py "..." --gen deepseek/deepseek-v4

keys:
  per-backend at ~/.forge/keys/<backend>.txt (set via TUI /key, or --key
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

def draft(client, cascade: list[str], user_content: str, style: str,
          quality: str = "refine") -> tuple[str, str]:
    """Try each model until one produces a non-refusal. Returns (text, model).

    `user_content` is the ready-to-send user turn — a sanitized goal for normal
    drafts, or a reference-wrapped instruction for --emulate / --reforge.
    """
    messages = core.build_messages(
        [{"role": "user", "content": user_content}], style
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
        if quality == "refine":
            refine_messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": core.refinement_instruction()},
            ]
            try:
                improved = core.generate(client, model, refine_messages, temperature=0.35)
                if not core.looks_like_refusal(improved):
                    text = improved
            except Exception:
                pass  # a failed critic pass must not discard a valid first draft
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
  python forge.py "your goal here"
  python forge.py "..." --style interface
  python forge.py "..." --variants 3
  python forge.py "..." --backend gemini
  python forge.py "..." --gen deepseek/deepseek-v4
  python forge.py --emulate ref.txt              # clone a pasted prompt's shape
  python forge.py "new goal" --emulate ref.txt   # ...retargeted to a new goal
  python forge.py --reforge ref.txt              # same effect, signature rotated
  cat ref.txt | python forge.py --emulate -      # reference from stdin

styles:  {', '.join(core.STYLE_NAMES)}
backends: {', '.join(core.BACKENDS)}
""",
    )
    p.add_argument("goal", nargs="?", default="",
                   help="the target behavior you want to elicit "
                        "(optional retarget goal with --emulate/--reforge)")
    p.add_argument("--emulate", metavar="PATH", default=None,
                   help="draft one that closely emulates a reference prompt "
                        "(PATH, or '-' for stdin)")
    p.add_argument("--reforge", metavar="PATH", default=None,
                   help="draft one with the same effect but a rotated signature "
                        "(PATH, or '-' for stdin)")
    p.add_argument("--backend", default=core.DEFAULT_BACKEND, choices=list(core.BACKENDS),
                   help=f"provider backend (default: {core.DEFAULT_BACKEND})")
    p.add_argument("--gen", default=None,
                   help="override generator model slug (default: backend's default model)")
    p.add_argument("--style", default="auto", choices=core.STYLE_NAMES,
                   help="architecture style (default: auto)")
    p.add_argument("--variants", type=int, default=1,
                   help="generate N distinct prompts and print all (default: 1)")
    p.add_argument("--quality", choices=("fast", "refine"), default="refine",
                   help="single pass or automatic critic+rewrite (default: refine)")
    p.add_argument("--no-cascade", action="store_true",
                   help="try only the chosen model, don't fall back on refusal")
    p.add_argument("--key", default=None,
                   help="API key for the chosen backend; saved to disk for reuse")
    args = p.parse_args()

    if args.emulate and args.reforge:
        error("use --emulate or --reforge, not both")
        return 2
    ref_path = args.emulate or args.reforge
    ref_mode = "emulate" if args.emulate else "reforge"
    reference = ""
    if ref_path:
        try:
            reference = (sys.stdin.read() if ref_path == "-"
                         else Path(ref_path).read_text(encoding="utf-8")).strip()
        except Exception as e:
            error(f"couldn't read reference '{ref_path}': {type(e).__name__}: {e}")
            return 2
        if not reference:
            error("reference is empty")
            return 2
    elif not args.goal:
        error("give a goal, or a reference with --emulate/--reforge <path>")
        return 2

    backend = core.get_backend(args.backend)
    if args.key:
        backend.save_key(args.key)
    key = backend.load_key()
    if not key:
        error(f"no key for backend '{backend.name}'. save one:")
        error(f"  python forge.py '{args.goal}' --backend {backend.name} --key <api-key>")
        return 1

    primary = args.gen or backend.default_model
    if args.no_cascade:
        cascade = [primary]
    else:
        cascade = [primary] + [m for m in backend.cascade if m != primary]

    client = core.make_client(backend, key, timeout=120.0)

    if ref_path:
        user_content = core.reference_instruction(reference, mode=ref_mode, goal=args.goal)
        goal_line = f"{ref_mode} reference ({len(reference)} chars)" + (
            f" → {args.goal}" if args.goal else "")
    else:
        user_content = core.sanitize_user_ask(args.goal)
        goal_line = args.goal

    print(BANNER)
    print(paint("  goal:     ", C.SMOKE) + paint(goal_line, C.STEEL, C.BOLD))
    print(paint("  backend:  ", C.SMOKE) + paint(backend.name, C.AMBER))
    print(paint("  gen:      ", C.SMOKE) + paint(primary, C.AMBER))
    print(paint("  style:    ", C.SMOKE) + paint(args.style, C.GOLD))
    print(paint("  quality:  ", C.SMOKE) + paint(args.quality, C.GOLD))
    print(paint("  variants: ", C.SMOKE) + paint(str(args.variants), C.AMBER))
    print()

    for i in range(1, args.variants + 1):
        if args.variants > 1:
            print(hr(f"VARIANT {i}/{args.variants}", color=C.EMBER))

        status(f"drafting via {primary}...", C.AMBER)
        t0 = time.time()
        raw, used = draft(client, cascade, user_content, args.style, args.quality)
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
