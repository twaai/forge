# Contributing to Forge

Forge 3.0 is a native desktop chat application for compiling and revising
production system prompts.

## Development setup

```bash
python -m venv .venv
python -m pip install -r requirements.txt pytest ruff pyinstaller
python -m pytest forge3/tests -q
```

Launch with `forge.bat` on Windows or `./forge.sh` on Linux and macOS.

## Architecture

- `forge3/web/` — desktop chat UI, saved-thread rail, model picker, and settings
- `forge3/forge_session.py` — Forge-only session and streaming orchestration
- `forge3/strength.py` — Forge 3.0 prompt compiler and recovery rails
- `forge3/core/` — shared provider, vault, history, and drafting primitives
- `forge.spec` — native PyInstaller build definition

Runtime data belongs under `~/.forge-3` and provider keys remain outside
the repository. Never commit `.env`, keys, chat history, configuration files,
generated drafts, or local build output.

## Pull-request checklist

- [ ] `python -m pytest forge3/tests -q` passes.
- [ ] `python -m compileall -q forge3` passes.
- [ ] The desktop window launches and can create, reopen, and revise a chat.
- [ ] New storage locations are covered by `.gitignore`.
- [ ] Dependencies are reflected in both dependency files.
- [ ] User-visible changes update the version and README.

Cross-platform changes must preserve Windows, Linux, Apple Silicon macOS, and
Intel macOS packaging.
