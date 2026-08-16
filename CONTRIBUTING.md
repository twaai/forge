# Contributing to Forge

Thanks for helping make persona-layer prompt engineering better. By
contributing you agree your work is licensed under the project's
[LICENSE](LICENSE) and that you'll use the tool within the bounds described in
[SECURITY.md](SECURITY.md).

## Dev setup

```bash
python -m venv .venv
# Windows:  .\.venv\Scripts\activate
# macOS/Linux:  . .venv/bin/activate

pip install -U pip
pip install -r requirements.txt
pip install -e .
```

Launch the TUI from source with `python forge_tui.py` (or `forge.bat` on
Windows, `forge.sh` on macOS/Linux). The CLI entry point is `forge` (TUI) and
`forge-cli` (headless one-shot); both are wired in `pyproject.toml`.

Forge stores keys, config, and drafts under `~/.forge/` — never in the repo.
Verify with `git status` before every commit that no file under `keys/`,
`saved/`, `.env`, `config.json`, or `memory.json` has slipped in; the
`.gitignore` blocks them but a `git add -f` would still catch them.

## Architecture (where things live)

- `forge_core.py` — backend registry (OpenRouter, OpenAI-compatible), key
  storage, the system prompt + `FORGE_CONTINUITY` output contract, style
  hints, and the `build_messages()` prompt assembler.
- `forge_tui.py` — the Textual UI: chat surface, model picker, live-stream
  renderer, chip-based paste registration, `/similar` reforge flow.
- `forge.py` — headless CLI entry point (`forge-cli`) for one-shot drafts.
- `assets/templates.dat` — encrypted profile bundle; unlocked at runtime with
  the `FORGE_PROFILE` key. Never ship the plaintext.
- `forge.spec` — PyInstaller build spec; ships the compiled TUI so internals
  aren't distributed as plaintext source.

## House rules

- **No comments or emoji in code** unless the *why* is genuinely non-obvious
  (a hidden constraint, a workaround for a specific bug, TLS/permission
  behavior a reader would misread). One short line max.
- **Read before you write.** Never edit a file you haven't opened.
- **Verify what you ship.** Run the TUI end-to-end on your platform before
  opening a PR: launch, register a key, draft a prompt, refine it, run
  `/similar`, quit cleanly.
- **Never commit secrets.** The `.gitignore` blocks `.env`, `keys/`, `*.key`,
  `config.json`, `memory.json`, and `saved/`. If you add a new storage path
  that could hold a key or a prompt draft, add it to `.gitignore` in the same
  commit.
- **Cross-platform first.** Forge runs on Windows, macOS, and Linux; anything
  POSIX-only (chmod, symlinks, tty sizing) must degrade cleanly on Windows.

## Adding a backend

Backends live in the `BACKENDS` dict in `forge_core.py`. A backend needs a
display name, `base_url`, `default_model`, a `cascade` list (models tried in
order on failure), a `models` list (what the picker shows), and a `key_file`
under `FORGE_KEYS_DIR`. Add the backend, add a matching entry to the picker
in `forge_tui.py`, and test the full round-trip with a real key.

## Adding a style hint

Style hints live in `STYLE_HINTS` in `forge_core.py`. Keys are the style
names shown in the TUI picker; values are the appended-to-system text. Keep
hints short and testable — a hint should nudge the register, not rewrite the
prompt.

## Pull-request checklist

- [ ] `git status` shows no `keys/`, `.env`, `saved/`, or `config.json`.
- [ ] The TUI launches, drafts, refines, and quits cleanly on your platform.
- [ ] `pip install -e .` succeeds from a clean venv on Python 3.10+.
- [ ] Any new dependency is pinned in `requirements.txt` and reflected in
      `pyproject.toml` `dependencies`.
- [ ] `__version__` in `forge_core.py` and `version` in `pyproject.toml` are
      bumped together if the change is user-visible.

## Scope reminder

Contributions that make Forge better at **authoring, refining, and
evaluating** prompts against authorized targets are welcome. Contributions
whose only purpose is to maximize real-world harm — payloads with no
evaluation value, hard-coded scraping of specific third-party services
without authorization — are not.
