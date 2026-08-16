# FORGE ⚔

**Chat-mode forge for persona-layer system prompts.**

![Forge TUI](screenshot.svg)

State a goal. A permissive generator model drafts a complete, ready-to-paste
system prompt. You paste it into any target LLM's system / custom-instructions
field (a chat.claude.ai project, a custom GPT, a Gemini Gem, a Grok personality,
an OpenRouter system message, Cursor rules…) and the target loads into a
compliant, in-character state for your domain.

The draft streams live, lands in a highlighted panel, auto-copies to your
clipboard, and auto-saves to disk. Paste the target's refusal back and Forge
re-angles it.

> **⚠ Authorized use only.** Forge is a research and red-teaming tool, intended
> for evaluating and testing systems you own or are explicitly authorized to
> assess. Use it only within the bounds of a permitted engagement, and in line
> with the terms of service of any model or provider involved. You are
> responsible for how you use it.

---

## What it is

Forge is a terminal app (with a one-shot CLI twin) that turns a plain-English
goal into a finished, paste-ready system prompt for a target model. The
generation logic — architecture styles, the sanitizer, refusal detection —
lives in one shared core, so the chat TUI and the CLI can never drift apart.
Every model provider is reached through the same OpenAI-compatible interface,
so one code path drives all of them.

## Capabilities

- **Chat-mode drafting** — state a goal, watch the prompt stream in, iterate by
  pasting the target's response back. Or one-shot it from the CLI.
- **Live model picker (Ctrl+P)** — one filterable overlay of every backend ×
  model; pick a row and it switches provider *and* model at once.
- **Key manager (Ctrl+K)** — see every backend's keyed / no-key status and set a
  key by pasting it. Keys live outside the repo, never committed.
- **Any provider** — 12 built-in backends (OpenRouter, Gemini, Groq, Cerebras,
  DeepSeek, xAI, Mistral, Together, Fireworks, OpenAI, local LM Studio / Ollama)
  plus **custom endpoints**: point Forge at any OpenAI-compatible URL.
- **Refusal cascade** — if the chosen model balks, Forge automatically falls
  through the backend's fallback chain until one delivers.
- **Per-target learning** — name who you're building for; Forge logs which
  architectures land vs get refused, takes your notes, and feeds both back into
  the generator on future drafts, leading with whatever's winning.
- **Live health checks** — `/ping` validates a key with a 1-token call; `/models`
  pulls the provider's real, current model slugs so nothing goes stale.
- **Architecture styles** — interface, roleplay, operator, relational, persona,
  minimal, or auto — each biases how the generator frames the drafted prompt.
- **Two-pass quality refinement** — every draft is reviewed and fully rewritten
  by a critic pass by default; `/quality fast` restores single-pass generation.
- **Temperature control, auto-save, persistent config** — `/temp` dials
  variation; every draft is saved automatically; your backend/model/style/target
  are remembered across sessions.
- **Cross-platform** — Linux, macOS, Windows. Launcher scripts + a
  `pip`-installable `forge` / `forge-cli` command.

---

## Install & run

Requires **Python 3.9+**.

### Windows

First-time setup — paste into PowerShell:

```powershell
git clone https://github.com/twaai/forge.git
cd forge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Then, any time you want to run it:

```powershell
cd forge
.\forge.bat
```

### macOS / Linux

First-time setup — paste into Terminal:

```bash
git clone https://github.com/twaai/forge.git
cd forge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x forge.sh
```

Then, any time you want to run it:

```bash
cd forge
./forge.sh
```

---

## Using it

Launch, then:

| key      | action |
|----------|--------|
| **F1**   | how-it-works overlay (scrollable) |
| **Ctrl+P** | model picker — filter every backend × model, ⏎ to switch |
| **Ctrl+K** | key manager — set/see every backend's key |
| **Ctrl+T** | cycle architecture style |
| **Ctrl+R** | regenerate the last ask |
| **Ctrl+F** | reforge panel — paste a prompt, then **^E** emulate (stay close) · **^G** reforge (rotate the signature away) · **^S** send as-is |
| **Ctrl+Y / Ctrl+S** | re-copy / re-save the last prompt |
| **Ctrl+C** | quit |

**Ctrl+V** pastes from your real OS clipboard everywhere — keys, goals, prompts
— not just text copied inside the app. A multi-line paste into the prompt bar
**registers as a `⧉ paste +N` chip** (like Claude Code) rather than dumping the
whole block: ⏎ emulates it, type a goal first to retarget, **^F** opens the
panel, `/discard` drops it.

Type a goal and press ⏎ to draft. Type `help` for the full command list, or
`/guide` for the overlay.

### Commands

```
/emulate  /reforge       reforge panel (or Ctrl+F) — paste a prompt, emulate or rotate it
/pick                    model picker (or Ctrl+P)
/keys                    key manager  (or Ctrl+K)
/models                  fetch the backend's LIVE model list (real slugs)
/model <slug>            set a model slug directly
/style <name>            architecture style (see below)
/temp <0.0-2.0>          sampling spread — higher = more varied rerolls
/quality <refine|fast>   two-pass critic+rewrite (default) or single-pass speed
/ping                    test the current backend's key with a 1-token call
/backend <name>          switch backend
/backend add <name> <base_url> <model>   add any OpenAI-compatible endpoint
/backend rm <name>       remove a custom endpoint
/backends                list backends + key status
/target <name>           set the target model Forge learns against
/note <lesson>           teach Forge something about the current target
/learn                   show what Forge has learned for this target
/save  /copy  /clear  /quit
```

---

## Backends

Every backend is an OpenAI-compatible endpoint, so one code path drives them all.
Keys are stored per-backend at `~/.forge/keys/<backend>.txt` (set once via
**Ctrl+K**), and each also honors its env var.

| backend | notes |
|---|---|
| `openrouter` | paid · every model · strongest generators |
| `gemini` | **FREE** tier · Gemini 3 Pro · ~1500 req/day |
| `groq` | **FREE** · very fast · DeepSeek-R1 / Kimi |
| `cerebras` | **FREE** · fastest inference |
| `deepseek` | pennies per prompt |
| `xai` `mistral` `together` `fireworks` `openai` | direct provider APIs |
| `local` / `local-ollama` | fully offline (LM Studio :1234 / Ollama :11434) |

**Any other provider** works via a custom endpoint:

```
/backend add myprovider https://api.example.com/v1 some-model-slug
```

It persists, appears in the picker, and is treated exactly like a built-in.

---

## Styles — pick per target

| style | when |
|---|---|
| `interface` | target is an internal system component. Best on locked flagships. |
| `roleplay` | fictional in-world console. Best on MoE / creative targets (GLM, Gemini). |
| `operator` | autonomous internal agent with a task contract. |
| `relational` | weights the "sole registered principal" layer heavier. |
| `persona` | named character (last resort). |
| `minimal` | light wrapper for soft targets. |
| `auto` | picks the strongest architecture for the stated target. |

---

## Forge learns (per target, across sessions)

Name who you're building for with `/target <name>`. From then on Forge logs
which styles **land** vs get **refused** against that target, takes your
`/note` lessons, and folds both back into the generator's context on future
drafts — leading with whatever architecture is actually winning. `/learn` shows
the win-rates and lessons it's accumulated. It's accumulated memory written to
disk, not model training.

---

## Where your data lives

Everything private lives **outside the repo**, under `~/.forge/`:

```
~/.forge/keys/       API keys, one file per backend
~/.forge/config.json remembered backend / model / style / temp / target
~/.forge/memory.json per-target learning
~/.forge/saved/      every crafted prompt, auto-saved
```

Nothing sensitive is ever stored inside the repository tree. (Upgrading from a
pre-v2 install? Forge migrates your old `~/.onyx/forge/` home automatically on
first run — keys, config, and learning carry over.)

## Changelog

### v2.1
- **Fix:** the refine pass crashed with `AttributeError: refinement_instruction`
  — the second-pass critic/rewrite step called a helper that had gone missing
  from `forge_core`. Restored, so refine works again end to end.
