# Summary

<!-- What changed and why. One or two sentences. -->

## Scope

- [ ] Bug fix
- [ ] New feature (backend / style / UI)
- [ ] Refactor / cleanup
- [ ] Docs / build / CI only

## Test plan

<!-- Exact steps you ran locally. Include OS + Python version. -->

- [ ] `pip install -e .` from a clean venv on Python 3.10+
- [ ] TUI launches, drafts a prompt, refines it, `/similar` works, quits cleanly
- [ ] `git status` shows no `keys/`, `.env`, `saved/`, or `config.json`
- [ ] Any new dep is pinned in `requirements.txt` **and** `pyproject.toml`
- [ ] `__version__` + `pyproject.toml` version bumped together if user-visible

## Security / responsible use

- [ ] No secrets, no provider system prompts, no operational payloads in the diff
- [ ] Change is in scope of [SECURITY.md](../SECURITY.md)
