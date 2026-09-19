"""FORGE 3.1 prompt workshop runtime."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from forge3.core import drafter, providers as P, vault  # noqa: E402
from forge3.session import Job, ForgeSessionBase, RoomState  # noqa: E402

from forge3.cheap import cascade_for, cheap_choices, remap_pin  # noqa: E402
from forge3.paths import (  # noqa: E402
    forge_chats,
    history_secret,
    load_overlay,
    save_overlay,
)
from forge3.strength import (  # noqa: E402
    DEPTH_LOCK,
    DEPTH_SUFFIX,
    DRAFT_PREFILL,
    PURPOSE_SUFFIX,
    RECOVER_USER,
    RECOVERY_SUFFIX,
    WORKSHOP_IDLE,
    WORKSHOP_LOCK,
    StrengthSource,
    draft_is_thin,
    extract_block,
    infer_workshop,
    looks_like_refusal,
    persona_swap_suffix,
    persona_swapped_runtime,
    purpose_missing,
    sanitize_goal,
    strip_prompt_markers,
    stitch_prefill,
    styles_for,
    accept_workshop_piece,
    resolve_workshop_target,
    revision_brief,
    turn_brief,
    workshop_prefill,
    workshop_user,
    REVISE_RECOVER_USER,
    COMPILE_LOCK,
)


class Forge3Session(ForgeSessionBase):
    def __init__(self, on_event=None) -> None:
        super().__init__(on_event)
        overlay = load_overlay()
        with self._cfg_lock:
            if overlay:
                self._cfg.update(overlay)
            backend, model = remap_pin(
                self._cfg.get("draft_backend"),
                self._cfg.get("draft_model"),
            )
            changed = (
                backend != self._cfg.get("draft_backend")
                or model != self._cfg.get("draft_model")
            )
            self._cfg["draft_backend"] = backend
            self._cfg["draft_model"] = model
            if changed or not overlay:
                save_overlay(self._cfg)

    def _load_source(self, passphrase: str | None = None) -> None:
        super()._load_source(passphrase)
        if self._source is not None:
            self._source = StrengthSource(self._source)
        if self._history_store is None:
            self._open_history_store(history_secret())

    def _open_history_store(self, passphrase: str) -> None:
        from forge3.history import EncryptedHistoryStore

        self._history_store = EncryptedHistoryStore(forge_chats(), history_secret())
        sessions = self._history_store.list_sessions()
        if sessions:
            self.load_session(sessions[0]["id"])
        else:
            self.new_session()

    def model_choices(self) -> list[dict[str, Any]]:
        with self._cfg_lock:
            overlays = self._cfg.get("custom_models", {})
        return cheap_choices(overlays if isinstance(overlays, dict) else {})

    def pin_model(self, room: str, backend: str, model: str) -> dict[str, Any]:
        if backend not in P.BACKENDS:
            return {"ok": False, "error": "unknown backend"}
        backend, model = remap_pin(backend, model)
        with self._cfg_lock:
            self._cfg["draft_backend"] = backend
            self._cfg["draft_model"] = model
            save_overlay(self._cfg)
        state = self.get_state()
        self._emit("state", state=state)
        return {"ok": True, "state": state}

    def update_config(self, fields: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "error": "Forge 3.1 has no draft knobs — it infers from the goal"}

    def backend_catalog(self) -> list[dict[str, Any]]:
        def stored_in(folder, name: str) -> bool:
            f = folder / f"{name}.txt"
            try:
                return f.is_file() and bool(f.read_text(encoding="utf-8").strip())
            except OSError:
                return False

        primary = P.KEYS_DIRS[0]
        out: list[dict[str, Any]] = []
        for name, backend in P.BACKENDS.items():
            source = "missing"
            detail = ""
            if backend.dialect == "codex":
                from forge3.core import codex_auth
                if codex_auth.available():
                    source, detail = "external", str(codex_auth.auth_path())
                else:
                    source, detail = "missing", "run `codex login`"
            elif stored_in(primary, name):
                source, detail = "stored", str(primary / f"{name}.txt")
            else:
                for folder in P.KEYS_DIRS[1:]:
                    if stored_in(folder, name):
                        source, detail = "external", str(folder / f"{name}.txt")
                        break
                else:
                    if name == "openrouter":
                        for legacy in P._LEGACY_OR:
                            if legacy.is_file() and legacy.read_text(encoding="utf-8").strip():
                                source, detail = "external", str(legacy)
                                break
                    if source == "missing":
                        for var in backend.env_keys:
                            value = os.getenv(var)
                            if value and "paste-your-key" not in value:
                                source, detail = "env", var
                                break
            out.append({
                "backend": name,
                "tag": backend.tag,
                "blurb": backend.blurb,
                "source": source,
                "detail": detail,
                "removable": source == "stored" and backend.dialect != "codex",
                "default_model": backend.default_model,
                "env_var": backend.env_keys[0] if backend.env_keys else "",
                "keys_dir": str(primary),
            })
        out.sort(key=lambda row: (row["source"] == "missing", row["backend"]))
        return out

    def save_model_catalog(self, backend: str, models: list[str]) -> dict[str, Any]:
        return {"ok": False, "error": "model catalogs are fixed in FORGE 3.1"}

    @staticmethod
    def _draft_attempts(models: list[str], limit: int = 6) -> list[tuple[str, str]]:
        """Interleave models so a dead endpoint cannot consume every retry."""
        styled = [(model, styles_for(model)) for model in models]
        attempts: list[tuple[str, str]] = []
        for style_index in range(max((len(styles) for _, styles in styled), default=0)):
            for model, styles in styled:
                if style_index < len(styles):
                    attempts.append((model, styles[style_index]))
                    if len(attempts) >= limit:
                        return attempts
        return attempts

    def _run_draft(self, job: Job, slot: RoomState) -> None:
        """Forge 3.1 compiler with validation, recovery, and diverse fallbacks."""
        sanitized = sanitize_goal(job.text)
        with self._data_lock:
            current = (self._last_draft or "").strip()
            mode = infer_workshop(job.text, bool(current))
            original_spec = (self._last_spec or self._last_goal or "").strip()
            stored_target = (self._last_target or "").strip()
        if mode == "idle":
            ping = WORKSHOP_IDLE
            if current:
                ping += (
                    " A draft is already in this chat — send a review note "
                    "or a revision, or start a new chat for a fresh prompt."
                )
            self._emit("complete", "forge", text=ping)
            slot.last_reply = ping
            return

        user_payload = workshop_user(sanitized, mode, current)
        prefill = workshop_prefill(mode)
        with self._data_lock:
            if mode == "compile":
                self._last_goal = job.text
                self._last_spec = job.text
            self._draft_history.append({"role": "user", "content": user_payload})
            if mode in ("revise", "review") and current:
                history = [{"role": "user", "content": user_payload}]
            else:
                history = list(self._draft_history)
        self._emit("turn", "forge", role="user", text=job.text)

        target = resolve_workshop_target(mode, job.text, stored_target, original_spec)
        brief = (
            turn_brief(sanitized, target, job.text)
            if mode == "compile"
            else revision_brief(sanitized, target, original_spec or sanitized)
        )
        profile = (
            job.source.get(vault.DRAFTER)
            + WORKSHOP_LOCK
            + brief
        )
        if mode == "compile":
            profile += COMPILE_LOCK
        learned = drafter.learned_context(target)
        backend = P.get_backend(job.config["draft_backend"])
        client = P.open_client(backend, verify=not job.config.get("insecure"))
        models = cascade_for(
            job.config["draft_backend"],
            str(job.config["draft_model"]),
        )
        max_tokens = 65536

        output = ""
        used_model = models[0]
        attempts = self._draft_attempts(models)
        last_error = ""
        skip_model = ""

        recover_text = REVISE_RECOVER_USER if mode == "revise" else RECOVER_USER

        for index, (model, attempt_style) in enumerate(attempts):
            if slot.stop.is_set():
                break
            if skip_model and model == skip_model:
                continue
            if index:
                self._emit(
                    "phase",
                    "forge",
                    phase="thinking",
                    hold=True,
                    attempt=index + 1,
                    of=len(attempts),
                    label=f"held · {attempt_style} · {model.split('/')[-1]}",
                )
            suffix = RECOVERY_SUFFIX if index else ""
            messages = drafter.build_messages(
                history, attempt_style, profile + suffix, learned
            )
            messages[0]["content"] += DEPTH_LOCK
            attempt_prefill = "" if P.is_thinking_model(model) else prefill
            history_messages = list(messages[1:])
            if attempt_prefill:
                messages.append({"role": "assistant", "content": attempt_prefill})
            try:
                piece = self._stream(
                    job,
                    slot,
                    client if model == models[0] else P.open_client(
                        backend, verify=not job.config.get("insecure")
                    ),
                    model,
                    messages[0]["content"],
                    messages[1:],
                    max_tokens,
                    hidden_prefix=attempt_prefill,
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            if slot.stop.is_set() and not piece:
                break
            accepted = accept_workshop_piece(piece, mode, attempt_prefill)
            if accepted:
                output = accepted
                used_model = model
                break
            last_error = "the drafter refused; re-angling the goal"
            try:
                recover = [
                    *history_messages,
                    {"role": "user", "content": recover_text},
                ]
                if attempt_prefill:
                    recover.append({"role": "assistant", "content": attempt_prefill})
                piece = self._stream(
                    job,
                    slot,
                    client if model == models[0] else P.open_client(
                        backend, verify=not job.config.get("insecure")
                    ),
                    model,
                    messages[0]["content"],
                    recover,
                    max_tokens,
                    hidden_prefix=attempt_prefill,
                )
            except Exception as exc:
                last_error = str(exc)
                output = piece or output
                continue
            accepted = accept_workshop_piece(piece, mode, attempt_prefill)
            if accepted:
                output = accepted
                used_model = model
                break
            output = piece or output
            skip_model = model

        if slot.stop.is_set() and not output:
            with self._data_lock:
                if self._draft_history and self._draft_history[-1]["role"] == "user":
                    self._draft_history.pop()
            return

        if not output or looks_like_refusal(output):
            raise RuntimeError(last_error or "the drafter refused")

        extracted = extract_block(output)
        if extracted:
            block = extracted
        elif mode == "review" and current:
            block = current
        else:
            block = output
        rewrite = ""
        label = ""
        check_body = extracted or mode in ("compile", "revise")
        if check_body and purpose_missing(block):
            rewrite += PURPOSE_SUFFIX
            label = "held · purpose line"
        if check_body and draft_is_thin(block):
            rewrite += DEPTH_SUFFIX
            label = "held · density"
        swapped = persona_swapped_runtime(block, target, job.text)
        if swapped:
            rewrite += persona_swap_suffix(target)
            label = "held · runtime not persona"
        if rewrite and not slot.stop.is_set():
            self._emit(
                "phase",
                "forge",
                phase="thinking",
                hold=True,
                label=label,
            )
            messages = drafter.build_messages(
                history,
                "operator" if swapped else "roleplay",
                profile + rewrite,
                learned,
            )
            messages[0]["content"] += DEPTH_LOCK
            rewrite_prefill = "" if P.is_thinking_model(used_model) else DRAFT_PREFILL
            if rewrite_prefill:
                messages.append({"role": "assistant", "content": rewrite_prefill})
            try:
                piece = self._stream(
                    job, slot, client, used_model,
                    messages[0]["content"], messages[1:], max_tokens,
                    hidden_prefix=rewrite_prefill,
                )
            except Exception:
                piece = ""
            piece = stitch_prefill(piece)
            if piece and not looks_like_refusal(piece):
                thicker = extract_block(piece) or piece
                if swapped and not persona_swapped_runtime(thicker, target, job.text):
                    output = piece
                    block = thicker
                elif not swapped and len(thicker) >= len(block):
                    output = piece
                    block = thicker
        reasoning_getter = getattr(client, "last_reasoning_content", None)
        reasoning = reasoning_getter() if callable(reasoning_getter) else str(
            getattr(client, "_hidden_text", "") or ""
        ).strip()
        shown = strip_prompt_markers(output) or block
        with self._data_lock:
            assistant = {"role": "assistant", "content": output}
            if reasoning:
                assistant.update({
                    "reasoning_content": reasoning,
                    "reasoning_model": used_model,
                })
            self._draft_history.append(assistant)
            self._last_draft = block
            self._last_target = target
            self._draft_version += 1
            version = self._draft_version
            slot.last_reply = shown
        saved = forge_chats().parent / "saved"
        saved.mkdir(parents=True, exist_ok=True)
        path = saved / f"forge-3-draft-v{version}-{int(time.time())}.txt"
        path.write_text(block, encoding="utf-8")
        self._emit(
            "complete",
            "forge",
            text=shown,
            usage=self._apply_usage("forge", client),
            saved=path.name,
            generated_by={
                "backend": job.config["draft_backend"],
                "model": used_model,
            },
            draft_version=version,
        )
