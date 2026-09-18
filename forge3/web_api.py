"""JavaScript bridge for the Forge 3.0 window. Same events, yellow skin."""

from __future__ import annotations

import json
import threading
from typing import Any

from forge3.forge_session import Forge3Session
from forge3.paths import drawer_label


class Api:
    def __init__(self) -> None:
        self._window: Any | None = None
        self._emit_lock = threading.Lock()
        self._session = Forge3Session(self._emit)

    def _bind_window(self, window: Any) -> None:
        self._window = window

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._window is None:
            return
        try:
            with self._emit_lock:
                self._window.evaluate_js(
                    "window.forge3Event("
                    f"{json.dumps(event)},"
                    f"{json.dumps(payload)}"
                    ")"
                )
        except Exception:
            pass

    def bootstrap(self) -> dict[str, Any]:
        return {
            "state": self._session.get_state(),
            "models": self._session.model_choices(),
            "sessions": self._session.list_sessions(),
            "room": self._session.room_snapshot("forge"),
            "backends": self._session.backend_catalog(),
            "drawer": drawer_label(),
        }

    def get_state(self) -> dict[str, Any]:
        return self._session.get_state()

    def unlock(self, passphrase: str) -> dict[str, Any]:
        return self._session.unlock(passphrase)

    def send(self, text: str) -> dict[str, Any]:
        return self._session.send("forge", text)

    def stop(self) -> dict[str, Any]:
        return self._session.stop("forge")

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._session.list_sessions()

    def new_session(self) -> dict[str, Any]:
        return self._session.new_session()

    def load_session(self, session_id: str) -> dict[str, Any]:
        return self._session.load_session(session_id)

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        return self._session.rename_session(session_id, title)

    def delete_session(self, session_id: str) -> dict[str, Any]:
        return self._session.delete_session(session_id)

    def model_choices(self) -> list[dict[str, Any]]:
        return self._session.model_choices()

    def pin_model(self, backend: str, model: str) -> dict[str, Any]:
        return self._session.pin_model("forge", backend, model)

    def backend_catalog(self) -> list[dict[str, Any]]:
        return self._session.backend_catalog()

    def update_config(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self._session.update_config(fields)

    def save_key(self, backend: str, key: str) -> dict[str, Any]:
        return self._session.save_key(backend, key)

    def delete_key(self, backend: str) -> dict[str, Any]:
        return self._session.delete_key(backend)

    def minimize(self) -> dict[str, Any]:
        if self._window is None:
            return {"ok": False, "error": "window is not ready"}
        self._window.minimize()
        return {"ok": True}

    def toggle_maximize(self) -> dict[str, Any]:
        if self._window is None:
            return {"ok": False, "error": "window is not ready"}
        self._window.toggle_fullscreen()
        return {"ok": True}

    def close(self) -> dict[str, Any]:
        if self._window is None:
            return {"ok": False, "error": "window is not ready"}
        self._window.destroy()
        return {"ok": True}
