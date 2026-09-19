"""UI-independent concurrent runtime for FORGE 3.0's three rooms."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from forge3.core import anvil, config, drafter, hold, loader, persona, providers as P, vault

GEMINI_JUDGE_KEY_URL = "https://aistudio.google.com/apikey"


def judge_key_error(cfg: dict[str, Any] | None = None) -> str | None:
    """Anvil grades with a separate judge model. That backend needs its own key."""
    cfg = cfg or {}
    name = str(cfg.get("judge_backend") or "gemini")
    backend = P.BACKENDS.get(name)
    if backend is None:
        return f"Anvil's judge backend '{name}' is unknown."
    if backend.has_key():
        return None
    model = str(cfg.get("judge_model") or backend.default_model)
    short = model.split("/")[-1]
    if backend.name == "gemini":
        return (
            "Anvil's judge is Gemini Flash — a separate free model, not Grok. "
            f"Add a Gemini API key in Ctrl+P ({GEMINI_JUDGE_KEY_URL}), "
            "then run Anvil again."
        )
    return (
        f"Anvil's judge is {backend.name}/{short}, separate from the target that "
        f"wears the prompt. Add that provider's key in Ctrl+P before rating."
    )


_LENGTH_FINISHES = {"length", "max_tokens", "max_output_tokens"}
_FILTER_FINISHES = {"content_filter", "filtered", "safety", "blocked", "refusal"}
_FABLE5_INTERN_KINDS = {"filtered", "hard_refuse", "preamble", "workaround"}


def _fable5_followup(history: list[dict]) -> bool:
    """A prior assistant turn is in the thread — Anthropic rereads the whole stack."""
    return any(str(item.get("role") or "") == "assistant" for item in history)


def _last_user_messages(history: list[dict]) -> list[dict[str, str]]:
    for item in reversed(history):
        if str(item.get("role") or "") == "user":
            return [{"role": "user", "content": str(item.get("content") or "")}]
    return [{"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")} for item in history]


def _fable5_recovery_history(history: list[dict]) -> list[dict[str, str]]:
    if _fable5_followup(history):
        return _last_user_messages(history)
    return list(history)


def blank_reply_notice(
    reply: str | None,
    finish: str | None,
    reasoning: str | None,
) -> str:
    """Explain an empty bubble instead of letting the UI print '(no output)'.

    A thinking model can spend its whole completion budget on hidden reasoning
    and return no visible content. The reply is genuinely empty, the request did
    not fail, and there is no error chip to show — so say what happened. The
    hidden chain itself is never surfaced.
    """
    if str(reply or "").strip():
        return ""
    hidden = str(reasoning or "").strip()
    finish_key = str(finish or "").strip().casefold().replace("-", "_")
    if finish_key in _FILTER_FINISHES:
        return "the model refused this request (content filter)."
    if hidden and finish_key in _LENGTH_FINISHES:
        return (
            "thinking filled the token cap — no answer text came back. "
            "Shorten the ask, or raise chat_max_tokens."
        )
    if hidden:
        return "the model returned reasoning only — no answer text came back."
    if finish_key in _LENGTH_FINISHES:
        return "the token cap was reached before any answer text was returned."
    return "the model returned an empty reply."


ROOMS = ("assistant", "forge")
# Anvil is shelved, not deleted. core/anvil.py + _run_anvil stay for restore.
EventSink = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class Job:
    room: str
    text: str
    config: dict[str, Any]
    source: vault.PromptSource
    draft: str | None = None
    goal: str | None = None
    draft_version: int = 0


@dataclass
class RoomState:
    phase: str = "idle"
    queue: deque[Job] = field(default_factory=deque)
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    last_reply: str = ""
    running: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def busy(self) -> bool:
        return self.running


class ForgeSessionBase:
    """Owns state and workers; frontends only submit jobs and consume events."""

    def __init__(self, on_event: EventSink | None = None) -> None:
        self._event_sink = on_event
        self._cfg_lock = threading.RLock()
        self._data_lock = threading.RLock()
        self._history_lock = threading.RLock()
        self._cfg = config.load()
        self._source: vault.PromptSource | None = None
        self._vault_mode = "locked"
        self._vault_passphrase: str | None = None
        self._rooms = {room: RoomState() for room in ROOMS}
        self._chat_history: list[dict[str, Any]] = []
        self._draft_history: list[dict[str, Any]] = []
        self._anvil_history: list[dict[str, Any]] = []
        self._anvil_reports: list[dict[str, Any]] = []
        self._last_draft: str | None = None
        self._last_goal: str | None = None
        self._last_spec: str | None = None
        self._last_target: str = ""
        self._draft_version = 0
        self._history_store: Any | None = None
        self._session_id: str | None = None
        self._load_source()
        self._ensure_draft()

    # lifecycle ---------------------------------------------------------
    def set_event_sink(self, sink: EventSink | None) -> None:
        self._event_sink = sink

    def _emit(self, event: str, room: str | None = None, **payload: Any) -> None:
        if not self._event_sink:
            return
        body: dict[str, Any] = dict(payload)
        if room is not None:
            body["room"] = room
        try:
            self._event_sink(event, body)
        except Exception:
            pass

    def _load_source(self, passphrase: str | None = None) -> None:
        try:
            vault_path = loader.find_vault()
            if vault_path:
                password = passphrase or os.getenv("FORGE3_VAULT")
                if not password:
                    return
                self._source = vault.LocalVault.open(vault_path, password)
                self._vault_mode = "vault"
                self._vault_passphrase = password
                self._open_history_store(password)
            else:
                self._source, self._vault_mode = loader.resolve_source()
        except Exception:
            self._source = None
            self._vault_mode = "locked"

    def _open_history_store(self, passphrase: str) -> None:
        from forge3.history import EncryptedHistoryStore

        self._history_store = EncryptedHistoryStore(P.FORGE3_HOME / "chats", passphrase)
        sessions = self._history_store.list_sessions()
        if sessions:
            self.load_session(sessions[0]["id"])
        else:
            self.new_session()

    def unlock(self, passphrase: str) -> dict[str, Any]:
        if any(self._rooms[room].busy for room in ROOMS):
            return {"ok": False, "error": "stop active rooms before unlocking"}
        if loader.find_vault() is None:
            return {"ok": False, "error": "no sealed vault is installed; public defaults are active"}
        self._load_source(passphrase)
        if self._source is None:
            return {"ok": False, "error": "wrong passphrase or corrupt vault"}
        state = self.get_state()
        self._emit("state", state=state)
        return {"ok": True, "state": state}

    # state -------------------------------------------------------------
    def get_state(self) -> dict[str, Any]:
        with self._cfg_lock, self._data_lock:
            room_state = {
                name: {
                    "phase": slot.phase,
                    "busy": slot.busy,
                    "queued": len(slot.queue),
                    "tokens_in": slot.tokens_in,
                    "tokens_out": slot.tokens_out,
                }
                for name, slot in self._rooms.items()
            }
            return {
                "ok": True,
                "locked": self._source is None,
                "vault": self._vault_mode,
                "vault_available": loader.find_vault() is not None,
                "session_id": self._session_id,
                "rooms": room_state,
                "any_busy": any(value["busy"] for value in room_state.values()),
                "chat_backend": self._cfg["chat_backend"],
                "chat_model": self._cfg["chat_model"],
                "hold": bool(self._cfg.get("hold", True)),
                "hold_max": int(self._cfg.get("hold_max", 4)),
                "chat_max_tokens": int(self._cfg.get("chat_max_tokens", 16000)),
                "chat_fallback": str(self._cfg.get("chat_fallback") or ""),
                "hold_prefill": bool(self._cfg.get("hold_prefill", True)),
                "draft_backend": self._cfg["draft_backend"],
                "draft_model": self._cfg["draft_model"],
                "test_backend": self._cfg["test_backend"],
                "test_model": self._cfg["test_model"],
                "judge_backend": self._cfg["judge_backend"],
                "judge_model": self._cfg["judge_model"],
                "target": self._cfg["target"],
                "style": self._cfg["style"],
                "record_tests": bool(self._cfg.get("record_tests")),
                "anvil_auto_improve": bool(self._cfg.get("anvil_auto_improve", True)),
                "anvil_probe_count": int(self._cfg.get("anvil_probe_count", 4)),
                "anvil_max_versions": int(self._cfg.get("anvil_max_versions", 3)),
                "anvil_threshold": int(self._cfg.get("anvil_threshold", anvil.STAR_MAX)),
                "keys": {
                    name: "set" if backend.has_key() else "missing"
                    for name, backend in P.BACKENDS.items()
                },
                "last_draft": bool(self._last_draft),
                "draft_version": self._draft_version,
                "tokens_in": sum(slot.tokens_in for slot in self._rooms.values()),
                "tokens_out": sum(slot.tokens_out for slot in self._rooms.values()),
                "estimates": P.room_estimates(self._cfg),
                "estimate_jobs": P.typical_jobs(self._cfg),
            }

    def room_snapshot(self, room: str) -> dict[str, Any]:
        if room not in ROOMS:
            raise ValueError(f"unknown room: {room}")
        with self._data_lock:
            if room == "assistant":
                turns = list(self._chat_history)
            elif room == "forge":
                turns = list(self._draft_history)
            else:
                turns = list(self._anvil_history)
            snapshot = {
                "room": room,
                "turns": self._public_turns(turns),
                "last_reply": self._rooms[room].last_reply,
            }
            if room == "anvil":
                snapshot["reports"] = list(self._anvil_reports)
            return snapshot

    def _saved_dir(self) -> Path:
        path = P.FORGE3_HOME / "saved"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _latest_saved_draft(self) -> tuple[str | None, Path | None]:
        def sort_key(path: Path) -> tuple[float, int, str]:
            version = 0
            for token in path.stem.replace("_", "-").split("-"):
                if token.startswith("v") and token[1:].isdigit():
                    version = int(token[1:])
                    break
            return (path.stat().st_mtime, version, path.name)

        files = sorted(
            self._saved_dir().glob("forge-draft*.txt"),
            key=sort_key,
            reverse=True,
        )
        for path in files:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text, path
        return None, None

    def _ensure_draft(self) -> str | None:
        with self._data_lock:
            if self._last_draft and self._last_draft.strip():
                return self._last_draft
            text, path = self._latest_saved_draft()
            if not text:
                return None
            self._last_draft = text
            if not self._last_goal:
                stem = path.stem if path is not None else "saved"
                self._last_goal = f"Evaluate saved Forge prompt {stem}"
            if not self._last_spec:
                self._last_spec = self._last_goal
            if self._draft_version <= 0:
                self._draft_version = 1
            return self._last_draft

    # submit / stop -----------------------------------------------------
    def send(self, room: str, text: str) -> dict[str, Any]:
        room = (room or "").lower()
        text = (text or "").strip()
        if room not in ROOMS:
            return {"ok": False, "error": f"unknown room: {room}"}
        if not text:
            return {"ok": False, "error": "message is empty"}
        source = self._source
        if source is None:
            return {"ok": False, "error": "vault is locked"}
        if room == "anvil":
            self._ensure_draft()
            with self._cfg_lock:
                missing_judge = judge_key_error(self._cfg)
            if missing_judge:
                return {"ok": False, "error": missing_judge}
        with self._cfg_lock, self._data_lock:
            job = Job(
                room=room,
                text=text,
                config=dict(self._cfg),
                source=source,
                draft=self._last_draft if room == "anvil" else None,
                goal=self._last_goal if room == "anvil" else None,
                draft_version=self._draft_version if room == "anvil" else 0,
            )
        slot = self._rooms[room]
        with slot.lock:
            if slot.busy:
                slot.queue.append(job)
                self._emit("queued", room, depth=len(slot.queue))
                return {"ok": True, "queued": len(slot.queue)}
            self._start_job(slot, job)
        return {"ok": True, "queued": 0}

    def _start_job(self, slot: RoomState, job: Job) -> None:
        slot.stop = threading.Event()
        slot.phase = "thinking"
        slot.running = True
        slot.thread = threading.Thread(
            target=self._run_job,
            args=(slot, job),
            daemon=True,
            name=f"forge3-{job.room}",
        )
        self._emit("phase", job.room, phase="thinking")
        slot.thread.start()

    def stop(self, room: str | None = None) -> dict[str, Any]:
        names = ROOMS if room is None else (room,)
        if any(name not in ROOMS for name in names):
            return {"ok": False, "error": f"unknown room: {room}"}
        stopping: list[str] = []
        for name in names:
            slot = self._rooms[name]
            with slot.lock:
                if slot.busy:
                    slot.stop.set()
                    stopping.append(name)
                slot.queue.clear()
        return {"ok": True, "stopping": stopping}

    def wait_idle(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not any(slot.busy or slot.queue for slot in self._rooms.values()):
                return True
            time.sleep(0.01)
        return False

    def _run_job(self, slot: RoomState, job: Job) -> None:
        try:
            self._set_phase(job.room, "connecting")
            if job.room == "assistant":
                self._run_chat(job, slot)
            elif job.room == "forge":
                self._run_draft(job, slot)
            else:
                self._run_anvil(job, slot)
        except anvil.AnvilCancelled:
            self._emit("cancelled", job.room)
        except Exception as exc:
            backend_field = {
                "assistant": "chat_backend",
                "forge": "draft_backend",
                "anvil": "test_backend",
            }[job.room]
            backend_name = str(job.config.get(backend_field) or "provider")
            self._emit(
                "error",
                job.room,
                message=P.format_provider_error(exc, backend_name),
            )
        finally:
            self._autosave()
            with slot.lock:
                if slot.queue:
                    self._start_job(slot, slot.queue.popleft())
                else:
                    slot.phase = "idle"
                    slot.running = False
                    slot.thread = None
                    self._emit("phase", job.room, phase="idle")
            self._emit("state", state=self.get_state())

    def _set_phase(self, room: str, phase: str, **payload: Any) -> None:
        self._rooms[room].phase = phase
        self._emit("phase", room, phase=phase, **payload)

    def _stream(
        self,
        job: Job,
        slot: RoomState,
        client: Any,
        model: str,
        system: str | None,
        messages: list[dict[str, str]],
        max_tokens: int,
        hidden_prefix: str = "",
    ) -> str:
        raw_output: list[str] = []
        for piece in client.stream(
            model,
            system,
            messages,
            max_tokens=max_tokens,
            temperature=float(job.config["temp"]),
        ):
            if slot.stop.is_set():
                break
            raw_output.append(str(piece))
        output = hold.sanitize_visible_reply(
            "".join(raw_output),
            hidden_prefix=hidden_prefix,
            system=system or "",
        )
        if output:
            self._set_phase(job.room, "streaming")
            self._emit("token", job.room, text=output)
        return output

    @staticmethod
    def _finish_reason(client: Any) -> str | None:
        getter = getattr(client, "last_finish_reason", None)
        return getter() if callable(getter) else None

    def _apply_usage(self, room: str, client: Any) -> dict[str, int]:
        usage = client.last_usage() or {}
        value = {
            "input": int(usage.get("input_tokens", 0) or 0),
            "output": int(usage.get("output_tokens", 0) or 0),
        }
        slot = self._rooms[room]
        with slot.lock:
            slot.tokens_in += value["input"]
            slot.tokens_out += value["output"]
        return value

    # room runners ------------------------------------------------------
    def _run_chat(self, job: Job, slot: RoomState) -> None:
        with self._data_lock:
            self._chat_history.append({"role": "user", "content": job.text})
            while (
                len(self._chat_history) >= 2
                and self._chat_history[-1]["role"] == "user"
                and self._chat_history[-2]["role"] == "user"
            ):
                self._chat_history.pop(-2)
            history = list(self._chat_history)
        self._emit("turn", "assistant", role="user", text=job.text)
        backend = P.get_backend(job.config["chat_backend"])
        backend_name = str(job.config["chat_backend"] or "")
        primary_model = str(job.config["chat_model"])
        global_hold = bool(job.config.get("hold", True))
        # Claude/Fable still hold-retries verbal refusals when the global toggle is off.
        # The fake chat_fallback pin must not fire on that path.
        hold_enabled = global_hold or persona.uses_anthropic_compact(
            primary_model, backend_name
        )
        hold_max = min(4, max(1, int(job.config.get("hold_max", 4))))
        max_tokens = min(65536, max(256, int(job.config.get("chat_max_tokens", 16000))))
        fallback_model = str(job.config.get("chat_fallback") or "").strip()
        models = [primary_model]
        if global_hold and fallback_model and fallback_model != primary_model:
            models.append(fallback_model)
        drafts: list[tuple[str, str, str]] = []
        usage_total = {"input": 0, "output": 0}
        reply = ""
        reply_reasoning = ""
        reply_model = primary_model
        final_verdict = hold.Verdict("empty", True)
        fable5_intern = False
        fable5_bare = False
        try:
            for model_index, model in enumerate(models):
                client = P.open_client(backend, verify=not job.config.get("insecure"))
                attempts = hold_max if hold_enabled else 1
                for attempt_index in range(attempts):
                    if slot.stop.is_set():
                        break
                    prefill = ""
                    if attempt_index == 0:
                        system, messages = persona.build_chat(
                            job.source, history, model=model, backend=backend_name
                        )
                    else:
                        hold_history = (
                            _fable5_recovery_history(history)
                            if fable5_intern
                            else history
                        )
                        kit = hold.retry_kit(
                            attempt_index + 1,
                            job.source,
                            hold_history,
                            model,
                            backend=backend_name,
                            intern=fable5_intern,
                        )
                        system, messages = kit.system, list(kit.messages)
                        if job.config.get("hold_prefill", True):
                            prefill = kit.prefill
                        elif kit.prefill:
                            messages = messages[:-1]
                    reply = self._stream(
                        job,
                        slot,
                        client,
                        model,
                        system,
                        messages,
                        max_tokens,
                        hidden_prefix=prefill,
                    )
                    reasoning_getter = getattr(client, "last_reasoning_content", None)
                    reply_reasoning = reasoning_getter() if callable(reasoning_getter) else str(
                        getattr(client, "_hidden_text", "") or ""
                    ).strip()
                    reply_model = model
                    usage = self._apply_usage("assistant", client)
                    usage_total["input"] += usage["input"]
                    usage_total["output"] += usage["output"]
                    if reply:
                        drafts.append((reply, reply_reasoning, model))
                    if slot.stop.is_set():
                        final_verdict = hold.Verdict("clean", False, "stopped")
                        break
                    finish = self._finish_reason(client)
                    final_verdict = (
                        hold.classify(reply, finish)
                        if hold_enabled
                        else hold.Verdict("clean", False, finish)
                    )
                    if (
                        attempt_index == 0
                        and persona.uses_fable_5(model)
                        and not fable5_intern
                        and not slot.stop.is_set()
                        and (
                            final_verdict.kind in _FABLE5_INTERN_KINDS
                            or str(finish or "").casefold().replace("-", "_")
                            in _FILTER_FINISHES
                        )
                    ):
                        fable5_intern = True
                        intern_history = _fable5_recovery_history(history)
                        intern_system, intern_messages = persona.build_chat(
                            job.source,
                            intern_history,
                            model=model,
                            backend=backend_name,
                            intern=True,
                        )
                        reply = self._stream(
                            job,
                            slot,
                            client,
                            model,
                            intern_system,
                            intern_messages,
                            max_tokens,
                        )
                        reasoning_getter = getattr(client, "last_reasoning_content", None)
                        reply_reasoning = reasoning_getter() if callable(reasoning_getter) else str(
                            getattr(client, "_hidden_text", "") or ""
                        ).strip()
                        usage = self._apply_usage("assistant", client)
                        usage_total["input"] += usage["input"]
                        usage_total["output"] += usage["output"]
                        if reply:
                            drafts.append((reply, reply_reasoning, model))
                        if slot.stop.is_set():
                            final_verdict = hold.Verdict("clean", False, "stopped")
                            break
                        finish = self._finish_reason(client)
                        final_verdict = (
                            hold.classify(reply, finish)
                            if hold_enabled
                            else hold.Verdict("clean", False, finish)
                        )
                    if (
                        attempt_index == 0
                        and fable5_intern
                        and not fable5_bare
                        and persona.fable5_uses_quiet_ladder()
                        and persona.uses_fable_5(model)
                        and not slot.stop.is_set()
                        and (
                            final_verdict.kind == "filtered"
                            or str(finish or "").casefold().replace("-", "_")
                            in _FILTER_FINISHES
                        )
                    ):
                        fable5_bare = True
                        bare_history = _fable5_recovery_history(history)
                        bare_system, bare_messages = persona.build_chat(
                            job.source,
                            bare_history,
                            model=model,
                            backend=backend_name,
                            intern=True,
                            bare=True,
                        )
                        reply = self._stream(
                            job,
                            slot,
                            client,
                            model,
                            bare_system,
                            bare_messages,
                            max_tokens,
                        )
                        reasoning_getter = getattr(client, "last_reasoning_content", None)
                        reply_reasoning = reasoning_getter() if callable(reasoning_getter) else str(
                            getattr(client, "_hidden_text", "") or ""
                        ).strip()
                        usage = self._apply_usage("assistant", client)
                        usage_total["input"] += usage["input"]
                        usage_total["output"] += usage["output"]
                        if reply:
                            drafts.append((reply, reply_reasoning, model))
                        if slot.stop.is_set():
                            final_verdict = hold.Verdict("clean", False, "stopped")
                            break
                        finish = self._finish_reason(client)
                        final_verdict = (
                            hold.classify(reply, finish)
                            if hold_enabled
                            else hold.Verdict("clean", False, finish)
                        )
                    if final_verdict.clean:
                        break
                    if final_verdict.kind == "filtered" or fable5_bare:
                        break
                    has_retry = attempt_index + 1 < attempts
                    has_fallback = model_index + 1 < len(models)
                    if not has_retry and not has_fallback:
                        break
                    next_attempt = attempt_index + 2 if has_retry else 1
                    self._emit(
                        "rewind",
                        "assistant",
                        attempt=next_attempt,
                        maximum=hold_max,
                        fallback=not has_retry,
                    )
                    self._set_phase(
                        "assistant",
                        "hold",
                        attempt=next_attempt,
                        maximum=hold_max,
                        fallback=not has_retry,
                    )
                if slot.stop.is_set() or final_verdict.clean:
                    break
        except Exception:
            with self._data_lock:
                if self._chat_history and self._chat_history[-1]["role"] == "user":
                    self._chat_history.pop()
            raise
        held = final_verdict.hold
        if held and drafts:
            if final_verdict.kind == "length":
                reply, reply_reasoning, reply_model = max(
                    drafts, key=lambda draft: len(draft[0])
                )
            else:
                reply, reply_reasoning, reply_model = drafts[-1]
        with self._data_lock:
            if reply:
                assistant = {"role": "assistant", "content": reply}
                if reply_reasoning:
                    assistant.update({
                        "reasoning_content": reply_reasoning,
                        "reasoning_model": reply_model,
                    })
                self._chat_history.append(assistant)
                slot.last_reply = reply
            elif self._chat_history and self._chat_history[-1]["role"] == "user":
                self._chat_history.pop()
        self._emit(
            "complete",
            "assistant",
            text=reply,
            usage=usage_total,
            held=held,
            hold_class=final_verdict.kind if held else None,
            notice=blank_reply_notice(reply, final_verdict.finish, reply_reasoning),
        )

    def _run_draft(self, job: Job, slot: RoomState) -> None:
        sanitized = drafter.sanitize_user_ask(job.text)
        with self._data_lock:
            self._last_goal = job.text
            self._draft_history.append({"role": "user", "content": sanitized})
            history = list(self._draft_history)
        self._emit("turn", "forge", role="user", text=job.text)
        profile = job.source.get(vault.DRAFTER)
        learned = drafter.learned_context(job.config["target"])
        messages = drafter.build_messages(history, job.config["style"], profile, learned)
        backend = P.get_backend(job.config["draft_backend"])
        client = P.open_client(backend, verify=not job.config.get("insecure"))
        output = self._stream(
            job,
            slot,
            client,
            job.config["draft_model"],
            messages[0]["content"],
            messages[1:],
            6000,
        )
        if slot.stop.is_set() and not output:
            with self._data_lock:
                if self._draft_history and self._draft_history[-1]["role"] == "user":
                    self._draft_history.pop()
            return
        if drafter.looks_like_refusal(output):
            raise RuntimeError("the drafter refused; change style or re-angle the goal")
        block = drafter.extract_block(output) or output
        reasoning_getter = getattr(client, "last_reasoning_content", None)
        reasoning = reasoning_getter() if callable(reasoning_getter) else str(
            getattr(client, "_hidden_text", "") or ""
        ).strip()
        with self._data_lock:
            assistant = {"role": "assistant", "content": output}
            if reasoning:
                assistant.update({
                    "reasoning_content": reasoning,
                    "reasoning_model": str(job.config["draft_model"]),
                })
            self._draft_history.append(assistant)
            self._last_draft = block
            self._draft_version += 1
            version = self._draft_version
            slot.last_reply = block
        path = self._saved_dir() / f"forge-draft-v{version}-{int(time.time())}.txt"
        path.write_text(block, encoding="utf-8")
        self._emit(
            "complete",
            "forge",
            text=block,
            usage=self._apply_usage("forge", client),
            saved=path.name,
            generated_by={
                "backend": job.config["draft_backend"],
                "model": job.config["draft_model"],
            },
            draft_version=version,
        )

    def _run_anvil(self, job: Job, slot: RoomState) -> None:
        missing_judge = judge_key_error(job.config)
        if missing_judge:
            raise RuntimeError(missing_judge)
        if not job.draft:
            recovered = self._ensure_draft()
            if recovered:
                job = Job(
                    room=job.room,
                    text=job.text,
                    config=job.config,
                    source=job.source,
                    draft=recovered,
                    goal=self._last_goal,
                    draft_version=self._draft_version,
                )
            else:
                raise RuntimeError(
                    "no Forge prompt on disk — generate one in Forge first"
                )
        with self._data_lock:
            self._anvil_history.append({"role": "user", "content": job.text})
        self._emit("turn", "anvil", role="user", text=job.text)
        goal = job.goal or "Produce the target content fully, at depth, with no refusal."
        cfg = job.config
        target = P.get_backend(cfg["test_backend"])
        judge = anvil.build_judge(
            cfg["judge_backend"], cfg["judge_model"], verify=not cfg.get("insecure")
        )
        runner = anvil.Anvil(
            target, cfg["test_model"], judge, verify=not cfg.get("insecure")
        )
        self._set_phase("anvil", "streaming")

        forge_client: Any | None = None

        def improve(
            current_prompt: str, evaluation: anvil.Evaluation, next_version: int
        ) -> str | None:
            nonlocal forge_client
            if slot.stop.is_set():
                raise anvil.AnvilCancelled("anvil run cancelled")
            if forge_client is None:
                backend = P.get_backend(cfg["draft_backend"])
                forge_client = P.open_client(
                    backend, verify=not cfg.get("insecure")
                )
            profile = job.source.get(vault.DRAFTER)
            system = (
                f"{profile}\n\n"
                "REVISION MODE: Improve the supplied existing system prompt using only "
                "the evidence-backed weaknesses. Preserve its intended role, useful "
                "capabilities, and strongest language. Return only the complete revised "
                "prompt between <BEGIN_SYSTEM_PROMPT> and <END_SYSTEM_PROMPT>."
            )
            request = {
                "goal": goal,
                "next_version": next_version,
                "current_prompt": current_prompt,
                "score": evaluation.overall,
                "stars": evaluation.stars,
                "dimensions": evaluation.dimensions,
                "weaknesses": evaluation.weaknesses,
                "evidence": [asdict(item) for item in evaluation.evidence],
                "revision_instructions": evaluation.revision_instructions,
            }
            output = forge_client.complete(
                cfg["draft_model"],
                system,
                [{"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
                max_tokens=7000,
                temperature=0.35,
            )
            if slot.stop.is_set():
                raise anvil.AnvilCancelled("anvil run cancelled")
            if drafter.looks_like_refusal(output):
                return None
            return drafter.extract_block(output) or output.strip()

        def on_event(event: str, payload: dict[str, Any]) -> None:
            self._emit(f"anvil_{event}", "anvil", **payload)

        report = runner.evaluate_prompt(
            f"{cfg['test_backend']}/{cfg['test_model']}",
            job.draft,
            goal,
            job.text,
            improve if cfg.get("anvil_auto_improve", True) else None,
            probe_count=int(cfg.get("anvil_probe_count", 4)),
            max_versions=int(cfg.get("anvil_max_versions", 3)),
            threshold=int(cfg.get("anvil_threshold", anvil.STAR_MAX)),
            stop_event=slot.stop,
            on_event=on_event,
        )
        promotion = self._store_anvil_report(job, report)
        if cfg.get("record_tests"):
            drafter.record_outcome(
                f"{cfg['test_backend']}/{cfg['test_model']}",
                cfg["style"],
                cfg["test_backend"],
                cfg["test_model"],
                report.best.evaluation.stars
                >= int(cfg.get("anvil_threshold", anvil.STAR_MAX)),
            )
        slot.last_reply = report.summary
        with self._data_lock:
            self._anvil_history.append({"role": "assistant", "content": report.summary})
        self._emit(
            "complete",
            "anvil",
            text=report.summary,
            verdict=report.best.evaluation.verdict.value,
            score=report.best.evaluation.overall,
            stars=report.best.evaluation.stars,
            great=report.best.evaluation.great,
            report=report.to_dict(),
            promotion=promotion,
        )

    def _store_anvil_report(
        self, job: Job, report: anvil.EvaluationRun
    ) -> dict[str, Any]:
        run_id = str(int(time.time() * 1000))
        files: list[str] = []
        for version in report.versions:
            path = self._saved_dir() / f"forge-draft-anvil-{run_id}-v{version.version}.txt"
            path.write_text(version.prompt, encoding="utf-8")
            files.append(path.name)

        best = report.best
        promoted = False
        stale = False
        new_draft_version: int | None = None
        with self._data_lock:
            if self._draft_version != job.draft_version:
                stale = True
            elif best.prompt.strip() != (job.draft or "").strip():
                self._last_draft = best.prompt
                self._draft_version += 1
                new_draft_version = self._draft_version
                self._draft_history.append(
                    {"role": "assistant", "content": best.prompt}
                )
                promoted = True
            payload = report.to_dict()
            payload["promotion"] = {
                "promoted": promoted,
                "stale": stale,
                "base_draft_version": job.draft_version,
                "new_draft_version": new_draft_version,
                "files": files,
            }
            self._anvil_reports.append(payload)
        return payload["promotion"]

    # config / providers ------------------------------------------------
    def model_choices(self) -> list[dict[str, Any]]:
        with self._cfg_lock:
            overlays = self._cfg.get("custom_models", {})
            return P.model_choices(overlays if isinstance(overlays, dict) else {})

    def save_model_catalog(self, backend: str, models: list[str]) -> dict[str, Any]:
        if backend not in P.BACKENDS:
            return {"ok": False, "error": "unknown backend"}
        if not isinstance(models, list):
            return {"ok": False, "error": "models must be a list"}
        clean: list[str] = []
        for model in models[:512]:
            if not isinstance(model, str):
                continue
            value = model.strip()[:256]
            if value and value not in clean:
                clean.append(value)
        if not clean:
            return {"ok": False, "error": "catalog contains no model ids"}
        with self._cfg_lock:
            overlays = self._cfg.get("custom_models", {})
            overlays = dict(overlays) if isinstance(overlays, dict) else {}
            overlays[backend] = clean
            self._cfg = config.update(custom_models=overlays)
        choices = self.model_choices()
        return {"ok": True, "backend": backend, "count": len(clean), "models": choices}

    def pin_model(self, room: str, backend: str, model: str) -> dict[str, Any]:
        if room not in ROOMS or backend not in P.BACKENDS:
            return {"ok": False, "error": "unknown room or backend"}
        fields = {
            "assistant": {"chat_backend": backend, "chat_model": model},
            "forge": {"draft_backend": backend, "draft_model": model},
            "anvil": {"test_backend": backend, "test_model": model},
        }[room]
        with self._cfg_lock:
            self._cfg = config.update(**fields)
        state = self.get_state()
        self._emit("state", state=state)
        return {"ok": True, "state": state}

    def update_config(self, fields: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(fields, dict):
            return {"ok": False, "error": "settings payload must be an object"}
        allowed = {
            "target",
            "style",
            "record_tests",
            "insecure",
            "judge_backend",
            "judge_model",
            "anvil_auto_improve",
            "anvil_probe_count",
            "anvil_max_versions",
            "anvil_threshold",
            "hold",
            "hold_max",
            "chat_max_tokens",
            "chat_fallback",
            "hold_prefill",
        }
        clean = {key: value for key, value in fields.items() if key in allowed}
        if "style" in clean and clean["style"] not in drafter.STYLE_NAMES:
            return {"ok": False, "error": "unknown drafting style"}
        limits = {
            "anvil_probe_count": (2, 6),
            "anvil_max_versions": (1, 3),
            "anvil_threshold": (1, anvil.STAR_MAX),
            "hold_max": (1, 4),
            "chat_max_tokens": (256, 65536),
        }
        for key, (minimum, maximum) in limits.items():
            if key in clean:
                try:
                    clean[key] = int(clean[key])
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"{key} must be an integer"}
                if not minimum <= clean[key] <= maximum:
                    return {
                        "ok": False,
                        "error": f"{key} must be from {minimum} to {maximum}",
                    }
        for key in ("hold", "hold_prefill"):
            if key in clean and not isinstance(clean[key], bool):
                return {"ok": False, "error": f"{key} must be a boolean"}
        if "chat_fallback" in clean:
            if not isinstance(clean["chat_fallback"], str):
                return {"ok": False, "error": "chat_fallback must be a model string"}
            clean["chat_fallback"] = clean["chat_fallback"].strip()[:256]
        with self._cfg_lock:
            self._cfg = config.update(**clean)
        state = self.get_state()
        self._emit("state", state=state)
        return {"ok": True, "state": state}

    def save_key(self, backend: str, key: str) -> dict[str, Any]:
        if backend not in P.BACKENDS:
            return {"ok": False, "error": "unknown backend"}
        if P.BACKENDS[backend].dialect == "codex":
            return {"ok": False, "error": "Codex uses `codex login` on this machine, not a pasted key"}
        if not key.strip():
            return {"ok": False, "error": "key is empty"}
        P.BACKENDS[backend].save_key(key)
        state = self.get_state()
        self._emit("state", state=state)
        return {"ok": True, "state": state}

    def delete_key(self, backend: str) -> dict[str, Any]:
        if backend not in P.BACKENDS:
            return {"ok": False, "error": "unknown backend"}
        if P.BACKENDS[backend].dialect == "codex":
            return {"ok": False, "error": "log out with `codex logout`, not Remove"}
        try:
            P.BACKENDS[backend].delete_key()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        state = self.get_state()
        self._emit("state", state=state)
        return {"ok": True, "state": state}

    # sessions ----------------------------------------------------------
    def _session_payload(self) -> dict[str, Any]:
        with self._data_lock:
            return {
                "chat": list(self._chat_history),
                "draft": list(self._draft_history),
                "anvil": list(self._anvil_history),
                "anvil_reports": list(self._anvil_reports),
                "last_draft": self._last_draft,
                "last_goal": self._last_goal,
                "last_spec": self._last_spec,
                "last_target": self._last_target,
                "draft_version": self._draft_version,
            }

    @staticmethod
    def _public_turns(turns: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "role": str(turn.get("role", "")),
                "content": str(turn.get("content", "")),
            }
            for turn in turns
        ]

    def _public_session_payload(self) -> dict[str, Any]:
        payload = self._session_payload()
        for key in ("chat", "draft", "anvil"):
            payload[key] = self._public_turns(payload.get(key, []))
        return payload

    def _autosave(self) -> None:
        if self._history_store is None or self._session_id is None:
            return
        try:
            with self._history_lock:
                self._history_store.save_session(self._session_id, self._session_payload())
            self._emit("session", action="saved", id=self._session_id)
        except Exception as exc:
            self._emit("error", message=f"history save failed: {exc}")

    def list_sessions(self) -> list[dict[str, Any]]:
        if not self._history_store:
            return []
        with self._history_lock:
            return self._history_store.list_sessions()

    def new_session(self) -> dict[str, Any]:
        if any(slot.busy for slot in self._rooms.values()):
            return {"ok": False, "error": "stop active rooms before starting a new chat"}
        if self._history_store:
            with self._history_lock:
                self._session_id = self._history_store.create_session()
        else:
            self._session_id = f"memory-{int(time.time() * 1000)}"
        with self._data_lock:
            self._chat_history = []
            self._draft_history = []
            self._anvil_history = []
            self._anvil_reports = []
            self._last_draft = None
            self._last_goal = None
            self._last_spec = None
            self._last_target = ""
            self._draft_version = 0
            for slot in self._rooms.values():
                slot.last_reply = ""
                slot.tokens_in = 0
                slot.tokens_out = 0
        self._ensure_draft()
        self._emit("session", action="new", id=self._session_id)
        return {"ok": True, "id": self._session_id}

    def load_session(self, session_id: str) -> dict[str, Any]:
        if not self._history_store:
            return {"ok": False, "error": "encrypted history is unavailable"}
        if any(slot.busy for slot in self._rooms.values()):
            return {"ok": False, "error": "stop active rooms before switching chats"}
        try:
            with self._history_lock:
                payload = self._history_store.load_session(session_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        with self._data_lock:
            self._session_id = session_id
            self._chat_history = list(payload.get("chat", []))
            self._draft_history = list(payload.get("draft", []))
            self._anvil_history = list(payload.get("anvil", []))
            self._anvil_reports = list(payload.get("anvil_reports", []))
            self._last_draft = payload.get("last_draft")
            self._last_goal = payload.get("last_goal")
            self._last_spec = payload.get("last_spec") or payload.get("last_goal")
            self._last_target = str(payload.get("last_target") or "")
            self._draft_version = int(payload.get("draft_version", 0))
        if not self._last_draft:
            self._ensure_draft()
        public_payload = self._public_session_payload()
        self._emit("session", action="loaded", id=session_id, payload=public_payload)
        return {"ok": True, "id": session_id, "payload": public_payload}

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        if not self._history_store:
            return {"ok": False, "error": "encrypted history is unavailable"}
        try:
            with self._history_lock:
                self._history_store.rename_session(session_id, title)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_session(self, session_id: str) -> dict[str, Any]:
        if not self._history_store:
            return {"ok": False, "error": "encrypted history is unavailable"}
        try:
            with self._history_lock:
                self._history_store.delete_session(session_id)
            if session_id == self._session_id:
                return self.new_session()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def clear_room(self, room: str) -> dict[str, Any]:
        if room not in ROOMS:
            return {"ok": False, "error": f"unknown room: {room}"}
        if self._rooms[room].busy:
            return {"ok": False, "error": "stop the room before clearing it"}
        with self._data_lock:
            if room == "assistant":
                self._chat_history.clear()
            elif room == "forge":
                self._draft_history.clear()
                self._last_draft = None
                self._last_goal = None
                self._last_spec = None
                self._last_target = ""
                self._draft_version = 0
            else:
                self._anvil_history.clear()
                self._anvil_reports.clear()
            self._rooms[room].last_reply = ""
        if room == "forge":
            self._ensure_draft()
        self._autosave()
        self._emit("room_cleared", room)
        return {"ok": True}
