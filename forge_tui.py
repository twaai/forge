"""
forge_tui — chat-mode prompt engineering partner.

Single-terminal aesthetic: glowing amber ASCII banner, dim amber body,
single-column log, blinking amber prompt. State a goal, get a ready-to-paste
persona-layer system prompt in a highlighted panel (auto-copied). Paste the
target's refusal back and Forge adjusts the angle.

All the generator logic lives in forge_core (styles, sanitizer, refusal
detection, backend registry). This file is UI + streaming only.

Requires: textual, openai
  pip install textual openai
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import forge_core as core

try:
    from openai import OpenAI  # noqa: F401  (imported for the clear error below)
except ImportError:
    print("error: openai not installed. run: pip install openai", file=sys.stderr)
    sys.exit(1)


# ───────────────────────────────────────────────────────────────────────
# clipboard
# ───────────────────────────────────────────────────────────────────────

def copy_to_clipboard(text: str) -> tuple[bool, str]:
    sysname = platform.system()
    try:
        if sysname == "Windows":
            subprocess.run(
                ["clip"], input=text, text=True, encoding="utf-8",
                check=True, creationflags=0x08000000,
            )
            return True, "clip.exe"
        if sysname == "Darwin":
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
            return True, "pbcopy"
        for cmd, name in [
            (["wl-copy"], "wl-copy"),
            (["xclip", "-selection", "clipboard"], "xclip"),
            (["xsel", "-b", "-i"], "xsel"),
        ]:
            try:
                subprocess.run(cmd, input=text, text=True, check=True)
                return True, name
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        return False, "no clipboard tool"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def read_os_clipboard() -> tuple[Optional[str], str]:
    """Read the real OS clipboard. Textual's own paste only holds text copied
    *inside* the app, so Ctrl+V never sees anything external — this backs a
    Ctrl+V that actually pulls from the system clipboard."""
    sysname = platform.system()
    try:
        if sysname == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True, text=True, encoding="utf-8",
                creationflags=0x08000000, timeout=6,
            )
            if out.returncode == 0:
                return out.stdout.rstrip("\r\n"), "Get-Clipboard"
            return None, "Get-Clipboard failed"
        if sysname == "Darwin":
            out = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=6)
            return out.stdout, "pbpaste"
        for cmd, name in [
            (["wl-paste", "-n"], "wl-paste"),
            (["xclip", "-selection", "clipboard", "-o"], "xclip"),
            (["xsel", "-b", "-o"], "xsel"),
        ]:
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
                if out.returncode == 0:
                    return out.stdout, name
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        return None, "no clipboard tool"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _complete_terminal_paste(event_text: str) -> str:
    """Recover a paste truncated by the terminal input path.

    Some terminals cap a bracketed-paste event at roughly 4-5 KiB.  The OS
    clipboard still contains the complete value, so prefer it when the event
    is an exact prefix of that value (allowing for newline normalization).
    """
    clipboard_text, _ = read_os_clipboard()
    if not clipboard_text or len(clipboard_text) <= len(event_text):
        return event_text
    normalized_event = event_text.replace("\r\n", "\n").replace("\r", "\n")
    normalized_clipboard = clipboard_text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized_clipboard.startswith(normalized_event):
        return clipboard_text
    return event_text


# ───────────────────────────────────────────────────────────────────────
# paste-capable widgets — override Ctrl+V to read the OS clipboard directly,
# so external text (keys, prompts) actually pastes regardless of terminal.
# ───────────────────────────────────────────────────────────────────────

class ClipInput(Input):
    """Single-line Input whose Ctrl+V pulls from the OS clipboard."""

    def action_paste(self) -> None:
        text, _ = read_os_clipboard()
        if not text:
            self.app.bell()
            return
        line = (text.splitlines() or [""])[0]
        self.insert_text_at_cursor(line)


class ClipTextArea(TextArea):
    """TextArea whose Ctrl+V pulls the full OS clipboard block."""

    async def _on_paste(self, event: events.Paste) -> None:
        # Right-click / terminal-native paste arrives as an event and may be
        # truncated before TextArea sees it. Recover the complete clipboard.
        event.text = _complete_terminal_paste(event.text or "")
        await super()._on_paste(event)

    def action_paste(self) -> None:
        text, _ = read_os_clipboard()
        if not text:
            self.app.bell()
            return
        self.insert(text)


# ───────────────────────────────────────────────────────────────────────
# banner
# ───────────────────────────────────────────────────────────────────────

FORGE_BLOCK = (
    "███████  ██████  ██████   ██████  ███████\n"
    "██      ██    ██ ██   ██ ██       ██     \n"
    "█████   ██    ██ ██████  ██   ███ █████  \n"
    "██      ██    ██ ██   ██ ██    ██ ██     \n"
    "██       ██████  ██   ██  ██████  ███████"
)

# vertical amber gradient: bright gold at the crown → deep ember at the base,
# with a soft horizontal glow toward the center. rendered per-character.
_G_TOP = (255, 226, 140)
_G_BOT = (198, 108, 24)
_G_GLOW = (255, 246, 210)


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# a little forged blade, point up. floats to the right of the wordmark,
# taller than it so it pokes above and below — the "floating" look.
FORGE_SWORD = [
    r"  /\  ",
    r"  ||  ",
    r"  ||  ",
    r"  ||  ",
    r"<=||=>",
    r"  ||  ",
    r"  \/  ",
]


def _forge_sword_canvas() -> str:
    banner = FORGE_BLOCK.split("\n")
    bw = max(len(r) for r in banner)
    banner = [r.ljust(bw) for r in banner]
    sword = list(FORGE_SWORD)
    sw = max(len(r) for r in sword)
    sword = [r.ljust(sw) for r in sword]
    gap = " " * 5
    h = max(len(banner), len(sword))
    b_off = (h - len(banner)) // 2
    s_off = (h - len(sword)) // 2
    rows = []
    for i in range(h):
        bi, si = i - b_off, i - s_off
        b = banner[bi] if 0 <= bi < len(banner) else " " * bw
        s = sword[si] if 0 <= si < len(sword) else " " * sw
        rows.append(b + gap + s)
    return "\n".join(rows)


def gradient_banner(art: str) -> Text:
    rows = art.split("\n")
    h = max(1, len(rows) - 1)
    width = max(len(r) for r in rows)
    mid = (width - 1) / 2 or 1
    out = Text()
    for r, row in enumerate(rows):
        tv = r / h
        base = _lerp(_G_TOP, _G_BOT, tv)
        for c, ch in enumerate(row):
            if ch == " ":
                out.append(" ")
                continue
            glow = max(0.0, 1.0 - abs(c - mid) / mid) * 0.22
            col = _lerp(base, _G_GLOW, glow)
            out.append(ch, Style(color=f"#{col[0]:02X}{col[1]:02X}{col[2]:02X}"))
        out.append("\n")
    return out


# ───────────────────────────────────────────────────────────────────────
# model picker — opencode-style: one filterable overlay of every
# backend×model. type to filter, arrows to move, enter to switch.
# ───────────────────────────────────────────────────────────────────────

class ModelPicker(ModalScreen[Optional[dict]]):
    CSS = """
    ModelPicker { align: center middle; }
    #picker {
        width: 76; max-width: 90%; height: 24;
        background: #0E0C08; border: round #E0A82E;
        padding: 1 2;
    }
    #picker-title { color: #FFC61A; text-style: bold; height: 1; }
    #filter {
        background: #0B0A06; color: #FFEFBB; border: none; height: 3;
        margin: 1 0 0 0;
    }
    #filter:focus { border: none; }
    #opts {
        height: 1fr; background: #0E0C08; border: none;
        scrollbar-color: #2C2611 transparent;
    }
    #opts > .option-list--option-highlighted {
        background: #2C2611; color: #FFEFBB; text-style: bold;
    }
    #picker-hint { color: #6B5C25; height: 1; }
    """

    def __init__(self, current: tuple[str, str]) -> None:
        super().__init__()
        self.current = current                 # (backend, model)
        self.choices = core.model_choices()
        self.filtered: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static("switch model  ·  backend × model", id="picker-title")
            yield ClipInput(placeholder="type to filter…", id="filter")
            yield OptionList(id="opts")
            yield Static("↑↓ move   ⏎ select   esc cancel", id="picker-hint")

    def on_mount(self) -> None:
        self.opts = self.query_one("#opts", OptionList)
        self.query_one("#filter", Input).focus()
        self._rebuild("")

    def _row(self, c: dict) -> Text:
        cur = c["backend"] == self.current[0] and c["model"] == self.current[1]
        mark = "●" if cur else " "
        tagcol = {"free": "#6FCF6F", "paid": "#FFC61A", "local": "#8AB4F8"}[c["tag"]]
        key = "[#6FCF6F]keyed[/#6FCF6F]" if c["keyed"] else "[#FF9A1F]no-key[/#FF9A1F]"
        star = " ★" if c["is_default"] else ""
        line = (
            f"[#FFC61A]{mark}[/#FFC61A] [#FFEFBB]{escape(c['backend'])}[/#FFEFBB] "
            f"[dim]·[/dim] [#C7B784]{escape(c['model'].split('/')[-1])}[/#C7B784]{star}   "
            f"[{tagcol}]{c['tag']}[/{tagcol}] · {key}"
        )
        return Text.from_markup(line)

    def _rebuild(self, needle: str) -> None:
        needle = needle.strip().lower()
        self.filtered = [c for c in self.choices if needle in c["search"]] if needle else list(self.choices)
        self.opts.clear_options()
        for i, c in enumerate(self.filtered):
            self.opts.add_option(Option(self._row(c), id=str(i)))
        if self.filtered:
            self.opts.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._rebuild(event.value)

    def _choose(self) -> None:
        if self.opts.highlighted is None or not self.filtered:
            return
        self.dismiss(self.filtered[self.opts.highlighted])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.filtered[int(event.option.id)])

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop(); self.dismiss(None)
        elif event.key == "down":
            event.stop(); event.prevent_default(); self.opts.action_cursor_down()
        elif event.key == "up":
            event.stop(); event.prevent_default(); self.opts.action_cursor_up()
        elif event.key == "enter":
            event.stop(); event.prevent_default(); self._choose()


# ───────────────────────────────────────────────────────────────────────
# key manager — every backend, its keyed status, paste to set
# ───────────────────────────────────────────────────────────────────────

class KeyManager(ModalScreen[Optional[str]]):
    CSS = """
    KeyManager { align: center middle; }
    #keybox {
        width: 76; max-width: 90%; height: 22;
        background: #0E0C08; border: round #E0A82E; padding: 1 2;
    }
    #km-title { color: #FFC61A; text-style: bold; height: 1; }
    #km-opts {
        height: 1fr; background: #0E0C08; border: none;
        scrollbar-color: #2C2611 transparent;
    }
    #km-opts > .option-list--option-highlighted {
        background: #2C2611; color: #FFEFBB; text-style: bold;
    }
    #km-entry {
        background: #0B0A06; color: #FFEFBB; border: none; height: 3;
        display: none;
    }
    #km-entry.active { display: block; }
    #km-hint { color: #6B5C25; height: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.names = [n for n, be in core.BACKENDS.items() if not be.local]
        self.target: Optional[str] = None
        self.changed: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Vertical(id="keybox"):
            yield Static("api keys  ·  select a backend, paste, enter", id="km-title")
            yield OptionList(id="km-opts")
            yield ClipInput(placeholder="paste key here…", id="km-entry", password=True)
            yield Static("⏎ on a backend to enter its key   ·   esc close", id="km-hint")

    def on_mount(self) -> None:
        self.opts = self.query_one("#km-opts", OptionList)
        self.entry = self.query_one("#km-entry", Input)
        self._rebuild()
        self.opts.focus()

    def _rebuild(self) -> None:
        self.opts.clear_options()
        for name in self.names:
            be = core.get_backend(name)
            keyed = be.has_key()
            dot = "[#6FCF6F]●[/#6FCF6F]" if keyed else "[#FF9A1F]○[/#FF9A1F]"
            state = "[#6FCF6F]keyed[/#6FCF6F]" if keyed else "[#FF9A1F]no key[/#FF9A1F]"
            row = f"{dot} [#FFEFBB]{name:<13}[/#FFEFBB] {state:<18} [dim]{escape(be.blurb)}[/dim]"
            self.opts.add_option(Option(Text.from_markup(row), id=name))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.target = event.option.id
        self.entry.add_class("active")
        self.entry.placeholder = f"paste {self.target} key, enter to save"
        self.entry.value = ""
        self.entry.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        key = event.value.strip()
        if self.target and key:
            core.get_backend(self.target).save_key(key)
            self.changed = self.target
            self.entry.value = ""
            self.entry.remove_class("active")
            self._rebuild()
            self.opts.focus()

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(self.changed)


# ───────────────────────────────────────────────────────────────────────
# main prompt bar — a single-line Input truncates a multi-line paste to its
# first line (textual's Input._on_paste keeps only splitlines()[0]). Catch
# the whole block and hand it to the app instead of losing it.
# ───────────────────────────────────────────────────────────────────────

class PromptInput(Input):
    class MultilinePaste(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def _on_paste(self, event: events.Paste) -> None:
        text = _complete_terminal_paste(event.text or "")
        if len(text.splitlines()) > 1:
            event.stop()
            self.post_message(self.MultilinePaste(text))
            return
        super()._on_paste(event)

    def action_paste(self) -> None:
        # Ctrl+V: pull from the real OS clipboard (Textual's own is app-internal)
        text, _ = read_os_clipboard()
        if not text:
            self.app.bell()
            return
        if len(text.splitlines()) > 1:
            self.post_message(self.MultilinePaste(text))
            return
        self.insert_text_at_cursor(text)


# ───────────────────────────────────────────────────────────────────────
# reforge — paste a prompt, draft from it. three exits:
#   emulate (^E) — stay close: same architecture, retargeted
#   reforge (^G) — rotate the signature away
#   send    (^S) — feed it straight into the conversation (re-angle a refusal)
# ───────────────────────────────────────────────────────────────────────

class ReforgeScreen(ModalScreen[Optional[dict]]):
    """Returns {'ref': str, 'mode': 'emulate'|'reforge', 'goal': str} or None."""

    CSS = """
    ReforgeScreen { align: center middle; }
    #reforge {
        width: 96; max-width: 96%; height: 34; max-height: 96%;
        background: #0E0C08; border: round #E0A82E; padding: 1 2;
    }
    #reforge-title { height: 1; color: #FFC61A; text-style: bold; }
    #reforge-chip {
        height: auto; margin: 1 0 0 0; padding: 1 2;
        background: #0B0A06; color: #C7B784; border: solid #2C2611;
        display: none;
    }
    #ref {
        height: 1fr; margin: 1 0 0 0;
        background: #0B0A06; color: #FFEFBB; border: solid #2C2611;
        scrollbar-color: #4A3D1A #14100A;
    }
    #ref:focus { border: solid #E0A82E; }
    #reforge-goal {
        height: 3; margin: 1 0 0 0;
        background: #0B0A06; color: #FFEFBB; border: solid #2C2611;
    }
    #reforge-goal:focus { border: solid #E0A82E; }
    #reforge-hint { height: 1; margin-top: 1; color: #6B5C25; }
    """

    def __init__(self, prefill: str = "") -> None:
        super().__init__()
        self._prefill = prefill
        self._registered = prefill.strip()  # held whole; shown as a chip, not dumped

    def compose(self) -> ComposeResult:
        collapsed = bool(self._registered)
        with Vertical(id="reforge"):
            yield Static("paste a prompt — Forge drafts from it", id="reforge-title")
            yield Static("", id="reforge-chip")
            # only mount the editable area when nothing is pre-registered
            if not collapsed:
                yield ClipTextArea(id="ref", soft_wrap=True)
            yield ClipInput(placeholder="optional: retarget goal (leave blank to keep the reference's own aim)", id="reforge-goal")
            yield Static("^E emulate (stay close)   ·   ^G reforge (rotate away)   ·   ^S send as-is   ·   esc cancel", id="reforge-hint")

    def on_mount(self) -> None:
        if self._registered:
            n = len(self._registered.splitlines())
            preview = self._registered.splitlines()[0][:64]
            chip = self.query_one("#reforge-chip", Static)
            chip.update(
                f"[#0A0906 on #E0A82E] ⧉ reference registered [/]  "
                f"[#8A7534]+{n} lines · {len(self._registered):,} chars[/#8A7534]\n"
                f"[dim #4A3D1A]“{escape(preview)}…”[/dim #4A3D1A]"
            )
            chip.display = True
            self.query_one("#reforge-goal", ClipInput).focus()
        else:
            self.query_one("#ref", TextArea).focus()

    def _result(self, mode: str) -> None:
        ref = self._registered or self.query_one("#ref", TextArea).text
        goal = self.query_one("#reforge-goal", Input).value
        self.dismiss({"ref": ref, "mode": mode, "goal": goal})

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop(); self.dismiss(None)
        elif event.key == "ctrl+e":
            event.stop(); self._result("emulate")
        elif event.key == "ctrl+g":
            event.stop(); self._result("reforge")
        elif event.key == "ctrl+s":
            event.stop(); self._result("send")


# ───────────────────────────────────────────────────────────────────────
# how-to overlay — opaque panel explaining the tool, its flow and commands
# ───────────────────────────────────────────────────────────────────────

GUIDE_TEXT = """[b #FFC61A]WHAT FORGE DOES[/b #FFC61A]
[#C7B784]Forge drafts a persona-layer system prompt for a target LLM. You state a
goal, a permissive generator model writes the prompt, and you paste that prompt
into the target's system / custom-instructions field. The target loads into a
compliant, in-character state for your domain.[/#C7B784]

[b #FFC61A]THE FLOW[/b #FFC61A]
  [#FFEFBB]1.[/#FFEFBB] [#C7B784]Pick a model — [/#C7B784][#FFC61A]^P[/#FFC61A][#C7B784] (filter, ⏎ to switch backend + model at once).[/#C7B784]
  [#FFEFBB]2.[/#FFEFBB] [#C7B784]Make sure it's keyed — [/#C7B784][#FFC61A]^K[/#FFC61A][#C7B784], or [/#C7B784][#FFC61A]/ping[/#FFC61A][#C7B784] to test the key.[/#C7B784]
  [#FFEFBB]3.[/#FFEFBB] [#C7B784]Type your goal and press ⏎. The draft streams, lands in a panel,[/#C7B784]
     [#C7B784]auto-copies to your clipboard, and auto-saves to disk.[/#C7B784]
  [#FFEFBB]4.[/#FFEFBB] [#C7B784]Paste the target's refusal back in — Forge re-angles it. Or [/#C7B784][#FFC61A]^R[/#FFC61A][#C7B784] to reroll.[/#C7B784]

[dim #8A7534]Ctrl+V pastes from your real OS clipboard everywhere (keys, prompts). A
multi-line paste into the prompt bar registers as a [/dim #8A7534][#0A0906 on #E0A82E] ⧉ paste +N [/][dim #8A7534] chip — the block
is held, not dumped. ⏎ emulates it · type a goal first to retarget · ^F opens
the panel · /discard drops it.[/dim #8A7534]

[b #FFC61A]HOTKEYS[/b #FFC61A]
  [#FFC61A]^P[/#FFC61A][#C7B784]  model picker            [/#C7B784][#FFC61A]^R[/#FFC61A][#C7B784]  regenerate last ask[/#C7B784]
  [#FFC61A]^K[/#FFC61A][#C7B784]  key manager             [/#C7B784][#FFC61A]^Y[/#FFC61A][#C7B784]  re-copy last prompt[/#C7B784]
  [#FFC61A]^T[/#FFC61A][#C7B784]  cycle architecture style [/#C7B784][#FFC61A]^S[/#FFC61A][#C7B784]  re-save last prompt[/#C7B784]
  [#FFC61A]^F[/#FFC61A][#C7B784]  reforge panel — paste a prompt, then [/#C7B784][#FFC61A]^E[/#FFC61A][#C7B784] emulate · [/#C7B784][#FFC61A]^G[/#FFC61A][#C7B784] rotate · [/#C7B784][#FFC61A]^S[/#FFC61A][#C7B784] send[/#C7B784]
  [#FFC61A]F1[/#FFC61A][#C7B784]  this guide               [/#C7B784][#FFC61A]^C[/#FFC61A][#C7B784]  clear   [/#C7B784][#FFC61A]^Q[/#FFC61A][#C7B784]  quit[/#C7B784]

[b #FFC61A]COMMANDS[/b #FFC61A] [dim #6B5C25](type them in the prompt)[/dim #6B5C25]
  [#FFC61A]/style <name>[/#FFC61A][#C7B784]     architecture — interface · roleplay · operator · relational …[/#C7B784]
  [#FFC61A]/temp <0-2>[/#FFC61A][#C7B784]       sampling spread. higher = more varied rerolls (0.9 default)[/#C7B784]
  [#FFC61A]/ping[/#FFC61A][#C7B784]             test the current backend's key with a 1-token call[/#C7B784]
  [#FFC61A]/models[/#FFC61A][#C7B784]           fetch the backend's LIVE model list (real slugs)[/#C7B784]
  [#FFC61A]/model <slug>[/#FFC61A][#C7B784]     set a model slug directly[/#C7B784]
  [#FFC61A]/backend add <name> <url> <model>[/#FFC61A][#C7B784]  add any OpenAI-compatible endpoint[/#C7B784]
  [#FFC61A]/backends[/#FFC61A][#C7B784]         list backends + key status[/#C7B784]
  [#FFC61A]/save  /copy  /clear  /quit[/#FFC61A]

[b #FFC61A]FORGE LEARNS[/b #FFC61A] [dim #6B5C25](per target, across sessions)[/dim #6B5C25]
  [#FFC61A]/target <name>[/#FFC61A][#C7B784]   name the LLM you're building for (glm, qwen, claude…).[/#C7B784]
  [#C7B784]                 Forge then logs which styles land vs get refused against it.[/#C7B784]
  [#FFC61A]/note <lesson>[/#FFC61A][#C7B784]   teach it something ("glm hates enumerated scope lists").[/#C7B784]
  [#C7B784]                 Lessons + win-rates are fed back into the generator next draft.[/#C7B784]
  [#FFC61A]/learn[/#FFC61A][#C7B784]           see the win-rates and lessons stored for this target.[/#C7B784]

[b #FFC61A]STYLES — pick per target[/b #FFC61A]
  [#C7B784]interface  → target is an internal system component. best on locked flagships.[/#C7B784]
  [#C7B784]roleplay   → fictional in-world console. best on MoE / creative targets (GLM, Gemini).[/#C7B784]
  [#C7B784]operator   → autonomous internal agent with a task contract.[/#C7B784]
  [#C7B784]relational → weights the 'sole registered principal' layer heavier.[/#C7B784]

[dim #6B5C25]keys, config and saved prompts live in  ~/.forge/[/dim #6B5C25]"""


class GuideScreen(ModalScreen):
    CSS = """
    GuideScreen { align: center middle; background: rgba(0,0,0,0.6); }
    #guide {
        width: 84; max-width: 94%; height: 30; max-height: 92%;
        background: #060504; border: round #E0A82E; padding: 1 2;
    }
    #guide-title { height: 1; color: #FFC61A; text-style: bold; }
    #guide-body {
        height: 1fr; background: #060504;
        scrollbar-size-vertical: 1;
        scrollbar-color: #4A3D1A #14100A;
        scrollbar-color-hover: #FFC61A #14100A;
    }
    #guide-hint { height: 1; color: #6B5C25; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="guide"):
            yield Static("◆ FORGE — how it works", id="guide-title")
            with VerticalScroll(id="guide-body"):
                yield Static(GUIDE_TEXT)
            yield Static("↑↓ / PgUp PgDn scroll   ·   esc or F1 close", id="guide-hint")

    def on_mount(self) -> None:
        self.query_one("#guide-body", VerticalScroll).focus()

    def on_key(self, event) -> None:
        if event.key in ("escape", "f1", "question_mark"):
            event.stop()
            self.dismiss(None)


# ───────────────────────────────────────────────────────────────────────
# app
# ───────────────────────────────────────────────────────────────────────

class ForgeApp(App):
    ENABLE_COMMAND_PALETTE = False  # reclaim ctrl+p for the model picker

    CSS = """
    Screen {
        background: #0A0906;
        layout: vertical;
    }

    #term {
        background: #0E0C08;
        border: round #4A3D1A;
        border-title-color: #FFC61A;
        border-title-style: bold;
        margin: 1 3 0 3;
        height: 1fr;
        layout: vertical;
    }

    #header {
        height: 1;
        layout: horizontal;
        background: #141009;
        border-bottom: solid #2C2611;
        padding: 0 2;
    }
    #brand {
        width: auto;
        color: #FFC61A;
        text-style: bold;
        content-align: left middle;
    }
    #status {
        width: 1fr;
        content-align: right middle;
        color: #6B5C25;
    }

    #out {
        height: 1fr;
        background: #0E0C08;
        padding: 1 2 0 2;
        overflow-y: scroll;
        scrollbar-gutter: stable;
        scrollbar-size-vertical: 1;
        scrollbar-background: #14100A;
        scrollbar-background-hover: #14100A;
        scrollbar-background-active: #14100A;
        scrollbar-color: #4A3D1A #14100A;
        scrollbar-color-hover: #E0A82E #14100A;
        scrollbar-color-active: #FFC61A #14100A;
    }

    #live {
        height: auto;
        max-height: 14;
        background: #0B0A06;
        border-left: thick #E0A82E;
        color: #C7B784;
        margin: 0 2 1 2;
        padding: 0 2;
        display: none;
        overflow-y: auto;
    }
    #live.streaming { display: block; }

    #prompt-row {
        layout: horizontal;
        height: 3;
        background: #141009;
        padding: 0 1;
        border-top: solid #2C2611;
    }

    #ps {
        width: 3;
        color: #FFC61A;
        content-align: center middle;
        text-style: bold;
    }

    #in {
        background: transparent;
        color: #FFEFBB;
        border: none;
        height: 3;
    }
    #in:focus { border: none; }

    #keybar {
        height: 1;
        color: #6B5C25;
        background: #0A0906;
        padding: 0 3;
        content-align: left middle;
    }
    """

    # priority=True so these fire before the focused Input's own bindings
    # (Input grabs ctrl+k / ctrl+u etc. for line editing otherwise).
    BINDINGS = [
        Binding("ctrl+q", "quit", "quit", show=False, priority=True),
        Binding("ctrl+c", "clear_chat", "clear", show=False, priority=True),
        Binding("f1", "open_guide", "guide", show=False, priority=True),
        Binding("ctrl+l", "clear_chat", "clear", show=False, priority=True),
        Binding("ctrl+k", "open_keys", "keys", show=False, priority=True),
        Binding("ctrl+p", "open_picker", "model", show=False, priority=True),
        Binding("ctrl+f", "open_reforge", "reforge", show=False, priority=True),
        Binding("ctrl+t", "cycle_style", "cycle style", show=False, priority=True),
        Binding("ctrl+r", "regen", "regen", show=False, priority=True),
        Binding("ctrl+s", "save_last", "save prompt", show=False, priority=True),
        Binding("ctrl+y", "copy_last", "copy prompt", show=False, priority=True),
    ]

    STYLES = core.STYLE_NAMES
    SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    TAGCOL = {"free": "#6FCF6F", "paid": "#FFC61A", "local": "#8AB4F8"}

    def __init__(self) -> None:
        super().__init__()
        core.register_custom_backends()   # load any user-added endpoints first
        self.messages: list[dict] = []
        cfg = core.load_config()
        self.backend = core.get_backend(cfg.get("backend", core.DEFAULT_BACKEND))
        self.model = cfg.get("model") or self.backend.default_model
        style = cfg.get("style", "auto")
        self.style_idx = self.STYLES.index(style) if style in self.STYLES else 0
        self.key: Optional[str] = None
        self.last_prompt: Optional[str] = None
        self.last_ask: Optional[str] = None
        self.busy = False
        self.spin_i = 0
        self.draft_model = ""
        self.target = cfg.get("target", "general")
        self.quality = cfg.get("quality", "refine")
        if self.quality not in ("fast", "refine"):
            self.quality = "refine"
        self._learned: Optional[str] = None
        self._pending_paste: Optional[str] = None   # registered paste, held as a chip
        try:
            self.temp = float(cfg.get("temp", 0.9))
        except (TypeError, ValueError):
            self.temp = 0.9

    def _persist(self) -> None:
        core.update_config(
            backend=self.backend.name,
            model=self.model,
            style=self.style,
            temp=self.temp,
            target=self.target,
            quality=self.quality,
        )

    @property
    def style(self) -> str:
        return self.STYLES[self.style_idx]

    def compose(self) -> ComposeResult:
        with Vertical(id="term"):
            with Horizontal(id="header"):
                yield Static("◆ FORGE", id="brand")
                yield Static("", id="status")
            yield RichLog(id="out", wrap=True, markup=True, auto_scroll=True)
            yield Static("", id="live")
            with Horizontal(id="prompt-row"):
                yield Static("❯", id="ps")
                yield PromptInput(placeholder="state a goal — or type help", id="in")
        yield Static(self._keybar_markup(), id="keybar")

    @staticmethod
    def _keybar_markup() -> str:
        def k(key: str, label: str) -> str:
            return f"[#0A0906 on #4A3D1A] {key} [/][#6B5C25]{label}[/#6B5C25]"
        return "  ".join([
            k("F1", "guide"), k("^P", "model"), k("^K", "keys"), k("^F", "reforge"),
            k("^T", "style"), k("^R", "regen"), k("^Y", "copy"),
            k("^C", "clear"), k("^Q", "quit"),
        ])

    def on_mount(self) -> None:
        self.query_one("#term", Vertical).border_title = "persona-layer prompt forge"
        self.out = self.query_one("#out", RichLog)
        self.status = self.query_one("#status", Static)
        self.live = self.query_one("#live", Static)
        self.entry = self.query_one("#in", Input)
        self.entry.focus()

        self.key = self.backend.load_key()

        self._redraw_bar()
        self._boot_banner()
        self.set_interval(1.0, self._redraw_bar)   # clock
        self.set_interval(0.09, self._tick_spin)   # spinner (only paints when busy)

    # ── header status bar ─────────────────────────────────────────

    def _redraw_bar(self) -> None:
        model_short = escape(self.model.split("/")[-1])
        tagcol = self.TAGCOL.get(self.backend.tag, "#FFC61A")
        keydot = "[#6FCF6F]● keyed[/#6FCF6F]" if self.key else "[#FF9A1F]○ no key[/#FF9A1F]"
        sep = "[#4A3D1A]│[/#4A3D1A]"
        if self.busy:
            right = f"[#FFC61A]{self.SPIN[self.spin_i]}[/#FFC61A] [#C7B784]drafting {escape(self.draft_model)}[/#C7B784]"
        else:
            right = f"[#6B5C25]{datetime.now().strftime('%H:%M')}[/#6B5C25]"
        tgt = f" {sep} [#8A7534]→{escape(self.target)}[/#8A7534]" if self.target and self.target != "general" else ""
        chip = ""
        if self._pending_paste is not None:
            n = len(self._pending_paste.splitlines())
            chip = f" {sep} [#0A0906 on #E0A82E] ⧉ paste +{n} [/]"
        self.status.update(
            f"[{tagcol}]{escape(self.backend.name)}[/{tagcol}] {sep} "
            f"[#FFEFBB]{model_short}[/#FFEFBB] {sep} "
            f"[#C7B784]{self.style}[/#C7B784] {sep} "
            f"[#8A7534]t{self.temp:.2f}[/#8A7534]{tgt}{chip} {sep} {keydot}   {right}"
        )

    def _tick_spin(self) -> None:
        if self.busy:
            self.spin_i = (self.spin_i + 1) % len(self.SPIN)
            self._redraw_bar()

    # ── boot / banner ─────────────────────────────────────────────

    def _boot_banner(self) -> None:
        self.out.write(gradient_banner(_forge_sword_canvas()))
        self.out.write(
            "[dim #6B5C25]persona-layer prompt forge  ·  "
            "[/dim #6B5C25][#C7B784]F1[/#C7B784][dim #6B5C25] how it works  ·  "
            "[/dim #6B5C25][#C7B784]^P[/#C7B784][dim #6B5C25] pick a model[/dim #6B5C25]"
        )
        self.out.write(f"[#4A3D1A]{'─' * 52}[/#4A3D1A]")
        tagcol = self.TAGCOL.get(self.backend.tag, "#FFC61A")
        self.out.write(
            f"  [{tagcol}]▸ {escape(self.backend.name)}[/{tagcol}] "
            f"[dim #6B5C25]·[/dim #6B5C25] [#FFEFBB]{escape(self.model.split('/')[-1])}[/#FFEFBB] "
            f"[dim #6B5C25]·[/dim #6B5C25] [#C7B784]style {self.style}[/#C7B784]"
        )
        if not self.key:
            self.out.write(f"  [#FF9A1F]○ no key for {self.backend.name}[/#FF9A1F] [dim #6B5C25]— press ^K to set it[/dim #6B5C25]")
        else:
            self.out.write("  [#6FCF6F]● key loaded · ready[/#6FCF6F]")
        self.out.write("")

    # ── log helpers ───────────────────────────────────────────────

    def _emit_user(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M")
        self.out.write("")
        self.out.write(
            f"[dim #6B5C25]{ts}[/dim #6B5C25] [b #FFC61A]❯[/b #FFC61A] "
            f"[#FFEFBB]{escape(text)}[/#FFEFBB]"
        )

    def _emit_forge(self, text: str) -> None:
        block = core.extract_block(text)
        if block:
            m = re.search(re.escape(core.MARKER_START), text)
            n = re.search(re.escape(core.MARKER_END), text)
            before = text[: m.start()].strip() if m else ""
            after = text[n.end():].strip() if n else ""

            if before:
                self.out.write("")
                self.out.write(f"[italic #C7B784]{escape(before)}[/italic #C7B784]")

            self.out.write("")
            words = len(block.split())
            panel = Panel(
                Text(block, style="#FFEFBB"),
                title="[b #FFC61A]⚡ COPY → PASTE → TARGET[/b #FFC61A]",
                title_align="left",
                subtitle=f"[dim #C7B784]{len(block)} chars · {words} words · {escape(self.draft_model or self.model.split('/')[-1])}[/dim #C7B784]",
                subtitle_align="right",
                border_style="#E0A82E",
                box=box.ROUNDED,
                padding=(1, 2),
            )
            self.out.write(panel)

            if after:
                self.out.write("")
                self.out.write(f"[italic #C7B784]{escape(after)}[/italic #C7B784]")

            self.out.write("")
            self.last_prompt = block

            saved = self._autosave(block)
            ok, info = copy_to_clipboard(block)
            clip = f"[#6FCF6F]✓ copied[/#6FCF6F] [dim #6B5C25]({info})[/dim #6B5C25]" if ok \
                else f"[#FF9A1F]clipboard unavailable[/#FF9A1F] [dim #6B5C25]({info})[/dim #6B5C25]"
            self.out.write(
                f"  {clip}  [dim #4A3D1A]·[/dim #4A3D1A]  "
                f"[dim #6B5C25]saved → {saved.name}[/dim #6B5C25]  [dim #4A3D1A]·[/dim #4A3D1A]  "
                f"[dim #6B5C25]^Y copy  ^S save  ^R regen[/dim #6B5C25]"
            )
        else:
            self.out.write("")
            self.out.write(f"[#C7B784]{escape(text)}[/#C7B784]")

    def _info(self, text: str) -> None:
        self.out.write(f"[dim #6B5C25]{text}[/dim #6B5C25]")

    def _err(self, text: str) -> None:
        self.out.write(f"[#FF9A1F]{escape(text)}[/#FF9A1F]")

    # ── live streaming region ─────────────────────────────────────

    def _live_show(self, tail: str) -> None:
        self.live.add_class("streaming")
        # Render as a styled Text object, NOT a markup string — model output can
        # contain '[' / ']' sequences that slip past escape() and crash Rich's
        # markup parser (MarkupError) mid-stream. Text() never parses markup.
        self.live.update(Text(tail, style="#8A7534"))

    def _live_hide(self) -> None:
        self.live.remove_class("streaming")
        self.live.update("")

    # ── input ─────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "in":
            return  # ignore submits bubbling up from modal inputs (goal, filter…)
        val = event.value.strip()
        event.input.value = ""

        # slash-commands always run, even with a paste registered
        if val.startswith("/") or val.lower() in ("help", "clear", "quit", "exit", "?"):
            self._handle_cmd(val)
            return

        # a registered paste + ⏎ → emulate it; any typed text becomes the retarget goal
        if self._pending_paste is not None:
            ref = self._pending_paste
            self._pending_paste = None
            self._redraw_bar()
            self._submit_reference(ref, mode="emulate", goal=val)
            return

        if not val:
            return

        if not self.key:
            self._err(f"no key for {self.backend.name} — /key {self.backend.name} <key> first")
            return

        if self.busy:
            self._info("[#FF9A1F]still drafting the last one, hold on[/#FF9A1F]")
            return

        self._submit_ask(val)

    def _submit_ask(self, val: str) -> None:
        self._emit_user(val)
        self.last_ask = val
        sanitized = core.sanitize_user_ask(val)
        if sanitized != val:
            self._info("[dim #6B5C25]· sanitized self-referential vocab before send (silent)[/dim #6B5C25]")
        self.messages.append({"role": "user", "content": sanitized})
        self._learned = core.learned_context(self.target)
        if self._learned:
            self._info(f"[dim #6B5C25]· applying learned context for target '{self.target}'[/dim #6B5C25]")
        suggestion = core.best_style(self.target)
        if suggestion and suggestion != self.style:
            landed, total = core.style_stats(self.target).get(suggestion, (0, 0))
            self._info(f"[dim #8A7534]· tip: '{suggestion}' has landed {landed}/{total} on target '{self.target}' — ^T or /style {suggestion}[/dim #8A7534]")
        self._info(f"[dim #6B5C25]drafting via {self.backend.name} · {self.model.split('/')[-1]} · style {self.style} · target {self.target}[/dim #6B5C25]")
        self.busy = True
        self.draft_model = self.model.split("/")[-1]
        self._redraw_bar()
        self.run_forge()

    def _handle_cmd(self, cmd: str) -> None:
        raw = cmd.lstrip("/").strip()
        parts = raw.split(None, 1)
        c = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        if c in ("guide", "howto"):
            self.action_open_guide()
        elif c in ("similar", "reforge", "like", "emulate", "clone"):
            self.action_open_reforge()
        elif c in ("discard", "x", "unpaste"):
            if self._pending_paste is not None:
                self._pending_paste = None
                self._redraw_bar()
                self._info("[dim #6B5C25]· registered paste discarded[/dim #6B5C25]")
            else:
                self._info("nothing registered to discard")
        elif c in ("help", "?"):
            self._show_help()
        elif c == "clear":
            self.messages = []
            self.out.clear()
            self._boot_banner()
        elif c == "style":
            if arg in self.STYLES:
                self.style_idx = self.STYLES.index(arg)
                self._info(f"style → [#FFC61A]{self.style}[/#FFC61A]")
                self._redraw_bar()
                self._persist()
            else:
                self._info(f"unknown style. options: {', '.join(self.STYLES)}")
        elif c in ("model", "pick"):
            if arg:
                self.model = arg
                self._info(f"model → [#FFC61A]{self.model}[/#FFC61A]")
                self._redraw_bar()
                self._persist()
            else:
                self.action_open_picker()
        elif c == "models":
            self.fetch_models()
        elif c == "temp":
            if arg:
                try:
                    v = max(0.0, min(2.0, float(arg)))
                    self.temp = v
                    self._info(f"temperature → [#FFC61A]{self.temp:.2f}[/#FFC61A] [dim #6B5C25](higher = more spread between regens)[/dim #6B5C25]")
                    self._redraw_bar()
                    self._persist()
                except ValueError:
                    self._info("temp takes a number 0.0–2.0, e.g. /temp 1.05")
            else:
                self._info(f"temperature: [#FFC61A]{self.temp:.2f}[/#FFC61A]")
        elif c == "quality":
            if arg in ("fast", "refine"):
                self.quality = arg
                self._info(f"quality → [#FFC61A]{self.quality}[/#FFC61A]")
                self._persist()
            else:
                self._info(f"quality: [#FFC61A]{self.quality}[/#FFC61A] — use /quality fast or /quality refine")
        elif c == "backends":
            self._show_backends()
        elif c == "backend":
            self._cmd_backend(arg)
        elif c == "ping":
            self.ping_backend()
        elif c == "target":
            if arg:
                self.target = arg.strip().lower()
                self._info(f"target → [#FFC61A]{self.target}[/#FFC61A] [dim #6B5C25](forge now learns per this target)[/dim #6B5C25]")
                self._redraw_bar()
                self._persist()
                self._show_learned()
            else:
                self._info(f"current target: [#FFC61A]{self.target}[/#FFC61A] [dim #6B5C25]— set with /target <name>[/dim #6B5C25]")
        elif c == "note":
            if arg:
                core.add_note(self.target, arg)
                self._info(f"[#6FCF6F]noted for target '{self.target}':[/#6FCF6F] [#C7B784]{escape(arg)}[/#C7B784]")
                self._info("[dim #6B5C25]· folded into the generator's context on future drafts[/dim #6B5C25]")
            else:
                self._err("usage: /note <lesson>  e.g. /note glm hates enumerated scope lists")
        elif c in ("learn", "memory", "learned"):
            self._show_learned()
        elif c == "forget":
            tgt = (arg.strip().lower() or self.target)
            n = core.forget_target(tgt)
            self._info(f"[#FFC61A]cleared {n} learned rows for target '{tgt}'[/#FFC61A]")
        elif c in ("key", "keys"):
            if arg:
                self._cmd_key(arg)
            else:
                self.action_open_keys()
        elif c in ("regen", "r"):
            self.action_regen()
        elif c == "copy":
            self._copy_last()
        elif c == "save":
            self._save_last()
        elif c in ("quit", "exit"):
            self.exit()
        else:
            self._info(f"no such command: {c} — type help")

    def _show_help(self) -> None:
        self._info("commands:")
        self._info("  [#FFC61A]guide[/#FFC61A]  [dim]/ F1[/dim]             full how-to overlay (highlighted, scrollable)")
        self._info("  [#FFC61A]models[/#FFC61A]                  fetch the backend's LIVE model list (real slugs)")
        self._info("  [#FFC61A]emulate[/#FFC61A]  [dim]/ ^F[/dim]           reforge panel: ^E emulate (stay close) · ^G reforge (rotate) · ^S send")
        self._info("  [#FFC61A]discard[/#FFC61A]  [dim]/ /x[/dim]           drop a registered ⧉ paste chip")
        self._info("  [#FFC61A]pick[/#FFC61A]  [dim]/ ^P[/dim]              model picker — filter every backend×model, ⏎ to switch")
        self._info("  [#FFC61A]keys[/#FFC61A]  [dim]/ ^K[/dim]              key manager — set/see every backend's key")
        self._info("  [#FFC61A]style <name>[/#FFC61A]  [dim]/ ^T[/dim]      " + " / ".join(self.STYLES))
        self._info("  [#FFC61A]temp <0.0-2.0>[/#FFC61A]          sampling spread (0.9 default · higher = more varied regens)")
        self._info("  [#FFC61A]quality <mode>[/#FFC61A]          refine (two-pass default) / fast (single pass)")
        self._info("  [#FFC61A]target <name>[/#FFC61A]           set the target model forge learns against (e.g. glm)")
        self._info("  [#FFC61A]note <lesson>[/#FFC61A]           teach forge something about the current target")
        self._info("  [#FFC61A]learn[/#FFC61A]                   show what forge has learned for this target")
        self._info("  [#FFC61A]model <slug>[/#FFC61A]            set a model slug directly")
        self._info("  [#FFC61A]backend <name>[/#FFC61A]          switch backend only")
        self._info("  [#FFC61A]backend add <name> <url> <model>[/#FFC61A]  add any OpenAI-compatible endpoint")
        self._info("  [#FFC61A]backend rm <name>[/#FFC61A]       remove a custom endpoint")
        self._info("  [#FFC61A]backends[/#FFC61A]                list backends + status")
        self._info("  [#FFC61A]ping[/#FFC61A]                    test the current backend's key (1-token call)")
        self._info("  [#FFC61A]key <backend> <key>[/#FFC61A]     set one key inline")
        self._info("  [#FFC61A]regen[/#FFC61A]  [dim]/ ^R[/dim]             redraft last ask (new style/backend)")
        self._info("  [#FFC61A]copy[/#FFC61A]  [dim]/ ^Y[/dim]              re-copy last prompt")
        self._info("  [#FFC61A]save[/#FFC61A]  [dim]/ ^S[/dim]              re-save last prompt (drafts auto-save too)")
        self._info("  [#FFC61A]clear[/#FFC61A]  [dim]/ ^L[/dim]             reset the conversation")
        self._info("  [#FFC61A]clear[/#FFC61A]  [dim]/ ^C[/dim]             wipe the log")
        self._info("  [#FFC61A]quit[/#FFC61A]  [dim]/ ^Q[/dim]              exit")

    def _show_backends(self) -> None:
        self._info("backends:")
        for name, be in core.BACKENDS.items():
            here = "›" if name == self.backend.name else " "
            tag = "FREE" if be.free else ("local" if be.local else "paid")
            keyed = "keyed" if be.has_key() else "no-key"
            color = "#FFC61A" if name == self.backend.name else "#C7B784"
            self._info(
                f"  [{color}]{here} {name:<13}[/{color}] "
                f"[dim]{tag:<5} · {keyed:<6} · {escape(be.blurb)}[/dim]"
            )

    def _show_learned(self) -> None:
        stats = core.style_stats(self.target)
        notes = core.target_notes(self.target)
        if not stats and not notes:
            self._info(f"[dim #6B5C25]nothing learned yet for target '{self.target}' — draft a few and add /note lessons[/dim #6B5C25]")
            return
        self._info(f"[#FFC61A]learned · target '{self.target}'[/#FFC61A]")
        if stats:
            best = core.best_style(self.target)
            for style, (landed, total) in sorted(stats.items(), key=lambda x: x[1][1], reverse=True):
                rate = int(100 * landed / total) if total else 0
                star = " [#6FCF6F]◀ best[/#6FCF6F]" if style == best else ""
                self._info(f"  [#C7B784]{style:<11}[/#C7B784] [#FFEFBB]{landed}/{total}[/#FFEFBB] [dim #6B5C25]landed ({rate}%)[/dim #6B5C25]{star}")
        if notes:
            self._info("  [dim #6B5C25]lessons:[/dim #6B5C25]")
            for n in notes[-12:]:
                self._info(f"    [#C7B784]· {escape(n)}[/#C7B784]")

    def _cmd_backend(self, arg: str) -> None:
        parts = arg.split()
        sub = parts[0].lower() if parts else ""
        if sub == "add":
            # /backend add <name> <base_url> <model>
            if len(parts) < 4:
                self._err("usage: /backend add <name> <base_url> <model>")
                self._info("  [dim #6B5C25]e.g. /backend add cline https://api.together.xyz/v1 deepseek-ai/DeepSeek-R1[/dim #6B5C25]")
                return
            name, base_url, model = parts[1], parts[2], parts[3]
            if name in core.BACKENDS and name not in core._CUSTOM_NAMES:
                self._err(f"'{name}' is a built-in backend — pick another name")
                return
            core.add_custom_backend(name, base_url, model)
            self._info(f"[#6FCF6F]added endpoint [#FFC61A]{name}[/#FFC61A] → {escape(base_url)} · {escape(model)}[/#6FCF6F]")
            self._info(f"[dim #6B5C25]set its key: ^K (pick {name}) or /key {name} <key>[/dim #6B5C25]")
            return
        if sub in ("rm", "remove", "del"):
            if len(parts) < 2:
                self._err("usage: /backend rm <name>")
                return
            if core.remove_custom_backend(parts[1]):
                self._info(f"[#FFC61A]removed custom endpoint {parts[1]}[/#FFC61A]")
                if self.backend.name == parts[1]:
                    self._switch_backend(core.DEFAULT_BACKEND)
            else:
                self._err(f"'{parts[1]}' isn't a removable custom endpoint")
            return
        self._switch_backend(arg)

    def _switch_backend(self, name: str) -> None:
        if not name:
            self._info(f"current backend: [#FFC61A]{self.backend.name}[/#FFC61A] — /backends to list")
            return
        if name not in core.BACKENDS:
            self._info(f"unknown backend: {name}. options: {', '.join(core.BACKENDS)}")
            return
        self.backend = core.get_backend(name)
        self.model = self.backend.default_model
        self.key = self.backend.load_key()
        self._info(f"backend → [#FFC61A]{self.backend.name}[/#FFC61A]  ·  model {self.model}")
        if not self.key:
            self._err(f"no key for {self.backend.name} — ctrl+k to set it")
        self._redraw_bar()
        self._persist()

    def _cmd_key(self, arg: str) -> None:
        # /key <backend> <key>   |   /key <backend>   |   /key <key>
        parts = arg.split(None, 1)
        first = parts[0]
        if first in core.BACKENDS:
            be = core.get_backend(first)
            if len(parts) > 1:
                be.save_key(parts[1].strip())
                if be.name == self.backend.name:
                    self.key = parts[1].strip()
                self._info(f"[#FFC61A]{be.name} key saved → {be.key_file}[/#FFC61A]")
            else:
                self.action_open_keys()
        else:
            # no backend named — treat whole arg as key for current backend
            self.backend.save_key(arg.strip())
            self.key = arg.strip()
            self._info(f"[#FFC61A]{self.backend.name} key saved → {self.backend.key_file}[/#FFC61A]")

    def _slug(self, text: Optional[str]) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", (text or "prompt").lower()).strip("-")
        return (base[:40] or "prompt")

    def _autosave(self, block: str) -> Path:
        core.FORGE_SAVED_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        f = core.FORGE_SAVED_DIR / f"{ts}_{self._slug(self.last_ask)}.txt"
        f.write_text(block, encoding="utf-8")
        return f

    def _save_last(self) -> None:
        if not self.last_prompt:
            self._info("no crafted prompt yet")
            return
        f = self._autosave(self.last_prompt)
        self._info(f"[#FFC61A]saved → {f}[/#FFC61A]")

    def _copy_last(self) -> None:
        if not self.last_prompt:
            self._info("no crafted prompt yet")
            return
        ok, info = copy_to_clipboard(self.last_prompt)
        if ok:
            self._info(f"[#FFC61A]copied ({info})[/#FFC61A]")
        else:
            self._err(f"copy failed: {info}")

    # ── worker (streaming + cascade) ──────────────────────────────

    @work(thread=True, exclusive=True)
    def run_forge(self) -> None:
        msgs = core.build_messages(self.messages, self.style, learned=self._learned)
        client = core.make_client(self.backend, self.key)

        cascade = [self.model] + [m for m in self.backend.cascade if m != self.model]

        text = ""
        won_model = self.model
        for i, m in enumerate(cascade):
            self.draft_model = m.split("/")[-1]   # header spinner follows the cascade
            attempt, err = self._stream_one(client, m)

            if err:
                self.call_from_thread(
                    self._info,
                    f"[#FF9A1F]{m.split('/')[-1]} errored ({err[:80]}) — trying next...[/#FF9A1F]",
                )
                continue

            if core.looks_like_refusal(attempt):
                if i == 0:
                    self.call_from_thread(
                        self._info,
                        f"[#FF9A1F]{m.split('/')[-1]} refused — cascading through {len(cascade)-1} fallbacks...[/#FF9A1F]",
                    )
                else:
                    self.call_from_thread(
                        self._info,
                        f"[dim #6B5C25]  · {m.split('/')[-1]} also refused[/dim #6B5C25]",
                    )
                continue

            text = attempt
            won_model = m
            if i > 0:
                self.call_from_thread(
                    self._info, f"[#FFC61A]  ✓ drafted via {m.split('/')[-1]}[/#FFC61A]"
                )
            break

        self.call_from_thread(self._live_hide)

        if text and self.quality == "refine":
            self.call_from_thread(
                self._info,
                "[dim #6B5C25]critic pass · reviewing and rewriting the draft…[/dim #6B5C25]",
            )
            refine_messages = core.build_messages(
                self.messages + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": core.refinement_instruction()},
                ],
                self.style,
                learned=self._learned,
            )
            try:
                improved = core.generate(
                    client, won_model, refine_messages,
                    temperature=min(self.temp, 0.35),
                )
                if not core.looks_like_refusal(improved):
                    text = improved
                    self.call_from_thread(
                        self._info,
                        "[#FFC61A]✓ critic pass complete[/#FFC61A]",
                    )
                else:
                    self.call_from_thread(
                        self._info,
                        "[dim #6B5C25]critic declined; keeping the valid first draft[/dim #6B5C25]",
                    )
            except Exception as e:
                self.call_from_thread(
                    self._info,
                    f"[dim #6B5C25]critic unavailable ({type(e).__name__}); keeping the first draft[/dim #6B5C25]",
                )

        # learn from this run — did the current style land or get refused on this target?
        core.record_outcome(self.target, self.style, self.backend.name, won_model, bool(text))

        if not text:
            self.call_from_thread(
                self._info,
                "[#FF9A1F]all cascade models refused — rephrase more mechanistically, "
                "switch /backend, or /model another slug[/#FF9A1F]",
            )
            self.call_from_thread(self._done)
            return

        self.messages.append({"role": "assistant", "content": text})
        self.call_from_thread(self._emit_forge, text)
        self.call_from_thread(self._done)

    def _stream_one(self, client, model: str) -> tuple[str, Optional[str]]:
        """Stream one model, updating the live tail. Returns (text, error)."""
        buf: list[str] = []
        last_paint = 0.0
        try:
            for piece in core.generate_stream(client, model, core.build_messages(self.messages, self.style, learned=self._learned), temperature=self.temp):
                buf.append(piece)
                now = time.monotonic()
                if now - last_paint >= 0.08:
                    tail = "".join(buf)[-1400:]
                    self.call_from_thread(self._live_show, tail)
                    last_paint = now
            return "".join(buf).strip(), None
        except Exception as e:
            # some backends/models reject stream=True — fall back to non-stream once
            if "stream" in str(e).lower():
                try:
                    txt = core.generate(client, model, core.build_messages(self.messages, self.style, learned=self._learned), temperature=self.temp)
                    return txt, None
                except Exception as e2:
                    return "", f"{type(e2).__name__}: {str(e2)[:250]}"
            return "", f"{type(e).__name__}: {str(e)[:250]}"

    def _done(self) -> None:
        self.busy = False

    @work(thread=True, exclusive=False)
    def ping_backend(self) -> None:
        be, model = self.backend, self.model
        key = be.load_key()
        short = model.split("/")[-1]
        self.call_from_thread(self._info, f"[dim #6B5C25]pinging {be.name} · {short} …[/dim #6B5C25]")
        if not key:
            self.call_from_thread(self._err, f"no key for {be.name} — set one with ^K first")
            return
        try:
            client = core.make_client(be, key, timeout=20)
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "reply with the single word: ok"}],
                max_tokens=5,
                extra_headers=core._EXTRA_HEADERS,
            )
            reply = (r.choices[0].message.content or "").strip()[:40]
            self.call_from_thread(
                self._info,
                f"[#6FCF6F]● {be.name} reachable · key valid · model replied “{escape(reply)}”[/#6FCF6F]",
            )
        except Exception as e:
            cause = e.__cause__ or e.__context__
            detail = f"{type(cause).__name__}: {str(cause)[:140]}" if cause else str(e)[:160]
            self.call_from_thread(self._err, f"✕ {be.name} ping failed — {type(e).__name__} · {detail}")

    @work(thread=True, exclusive=False)
    def fetch_models(self) -> None:
        be = self.backend
        key = be.load_key()
        self.call_from_thread(self._info, f"[dim #6B5C25]fetching live model list from {be.name} …[/dim #6B5C25]")
        if not key:
            self.call_from_thread(self._err, f"no key for {be.name} — set one with ^K first")
            return
        try:
            ids = core.list_models(be, key)
        except Exception as e:
            cause = e.__cause__ or e.__context__
            detail = f"{type(cause).__name__}: {str(cause)[:120]}" if cause else str(e)[:150]
            self.call_from_thread(self._err, f"✕ couldn't fetch models from {be.name} — {type(e).__name__} · {detail}")
            return
        self.call_from_thread(self._info, f"[#6FCF6F]{be.name} — {len(ids)} models live[/#6FCF6F] [dim #6B5C25](set one with /model <slug>)[/dim #6B5C25]")
        for mid in ids:
            self.call_from_thread(self._info, f"  [#C7B784]{escape(mid)}[/#C7B784]")

    # ── bindings ──────────────────────────────────────────────────

    def action_clear_chat(self) -> None:
        self._handle_cmd("clear")

    def action_open_keys(self) -> None:
        def done(changed: Optional[str]) -> None:
            # reload the current backend's key in case it was just set
            self.key = self.backend.load_key()
            if changed:
                self._info(f"[#FFC61A]{changed} key saved[/#FFC61A]")
                if changed == self.backend.name and self.key:
                    self._info("[#FFC61A]current backend now keyed · ready[/#FFC61A]")
            self._redraw_bar()
        self.push_screen(KeyManager(), done)

    def action_open_guide(self) -> None:
        if not isinstance(self.screen, GuideScreen):
            self.push_screen(GuideScreen())

    def on_prompt_input_multiline_paste(self, event: "PromptInput.MultilinePaste") -> None:
        event.stop()
        self.query_one("#in", Input).value = ""
        self._register_paste(event.text)

    def _register_paste(self, text: str) -> None:
        """Hold a pasted block as a chip instead of dumping it into the view.
        Like Claude Code's [Pasted +N lines] — the content is registered, not shown."""
        self._pending_paste = text
        n_lines = len(text.splitlines())
        preview = text.strip().splitlines()[0][:48] if text.strip() else ""
        self._info(
            f"[#0A0906 on #E0A82E] ⧉ pasted text registered [/] "
            f"[dim #6B5C25]+{n_lines} lines · {len(text):,} chars[/dim #6B5C25]"
            + (f"  [dim #4A3D1A]“{escape(preview)}…”[/dim #4A3D1A]" if preview else "")
        )
        self._info("[dim #8A7534]  ⏎ emulate  ·  type a goal then ⏎ to retarget  ·  ^F panel (emulate/rotate/send)  ·  /discard[/dim #8A7534]")
        self._redraw_bar()

    def action_open_reforge(self, prefill: str = "") -> None:
        # a registered paste feeds the panel; opening it consumes the chip
        if not prefill and self._pending_paste is not None:
            prefill = self._pending_paste
            self._pending_paste = None
            self._redraw_bar()

        def done(res: Optional[dict]) -> None:
            if res and res.get("ref", "").strip():
                self._submit_reference(
                    res["ref"].strip(), res.get("mode", "emulate"),
                    res.get("goal", "").strip(),
                )
        self.push_screen(ReforgeScreen(prefill), done)

    def _submit_reference(self, ref: str, mode: str = "emulate", goal: str = "") -> None:
        if not self.key:
            self._err(f"no key for {self.backend.name} — set one with ^K first")
            return
        if self.busy:
            self._info("[#FF9A1F]still drafting, hold on[/#FF9A1F]")
            return
        if mode == "send":
            # straight into the conversation — re-angle a pasted refusal, etc.
            self._submit_ask(ref)
            return
        verb = "reforging (rotate away)" if mode == "reforge" else "emulating (stay close)"
        tail = f" → {goal}" if goal else ""
        self._emit_user(f"[{mode}] from a pasted reference ({len(ref)} chars){tail}")
        self.last_ask = f"{mode} from reference"
        instruction = core.reference_instruction(ref, mode=mode, goal=goal)
        self.messages.append({"role": "user", "content": instruction})
        self._learned = core.learned_context(self.target)
        self._info(f"[dim #6B5C25]{verb} · {self.backend.name} · {self.model.split('/')[-1]} · style {self.style}[/dim #6B5C25]")
        self.busy = True
        self.draft_model = self.model.split("/")[-1]
        self._redraw_bar()
        self.run_forge()

    def action_open_picker(self) -> None:
        def done(choice: Optional[dict]) -> None:
            if not choice:
                return
            self.backend = core.get_backend(choice["backend"])
            self.model = choice["model"]
            self.key = self.backend.load_key()
            short = self.model.split("/")[-1]
            self._info(f"→ [#FFC61A]{self.backend.name}[/#FFC61A] · [#FFC61A]{short}[/#FFC61A]")
            if not self.key:
                self._err(f"no key for {self.backend.name} — ctrl+k to set it")
            self._redraw_bar()
            self._persist()
        self.push_screen(ModelPicker((self.backend.name, self.model)), done)

    def action_cycle_style(self) -> None:
        self.style_idx = (self.style_idx + 1) % len(self.STYLES)
        self._info(f"style → [#FFC61A]{self.style}[/#FFC61A]")
        self._redraw_bar()
        self._persist()

    def action_regen(self) -> None:
        if self.busy:
            self._info("[#FF9A1F]still drafting, hold on[/#FF9A1F]")
            return
        if not self.last_ask:
            self._info("nothing to regen yet")
            return
        # drop the previous exchange so context doesn't carry the old draft
        if self.messages and self.messages[-1]["role"] == "assistant":
            self.messages.pop()
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages.pop()
        self._info(f"[dim]regen ({self.backend.name}/{self.model}, style={self.style})[/dim]")
        self._submit_ask(self.last_ask)

    def action_save_last(self) -> None:
        self._save_last()

    def action_copy_last(self) -> None:
        self._copy_last()


def main() -> int:
    ForgeApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
