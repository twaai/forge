"""Encrypted-at-rest conversation storage for FORGE 3.0."""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_MAGIC = "FORGE3-HISTORY-1"
_ITERATIONS = 600_000


class HistoryError(RuntimeError):
    pass


def _plain(text: Any) -> str:
    return " ".join(str(text or "").split())


def _primary_turns(payload: dict[str, Any]) -> list:
    """FORGE 3.0/Lite/Dev store the thread in chat. Forge 3 stores it in draft."""
    chat = payload.get("chat") or []
    if isinstance(chat, list) and chat:
        return chat
    draft = payload.get("draft") or []
    return draft if isinstance(draft, list) else []


def _first_user_title(turns: list) -> str:
    for item in turns:
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "") != "user":
            continue
        text = _plain(item.get("content"))
        if text:
            return text[:60]
    return ""


def _preview_text(turns: list) -> str:
    for item in reversed(turns):
        if not isinstance(item, dict):
            continue
        text = _plain(item.get("content"))
        if text:
            return text[:160]
    return ""


class EncryptedHistoryStore:
    def __init__(self, directory: str | Path, passphrase: str) -> None:
        if not passphrase:
            raise HistoryError("history requires a non-empty vault passphrase")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._passphrase = passphrase
        self._index_path = self.directory / "index.forge3"
        if not self._index_path.exists():
            self._write_encrypted(self._index_path, {"version": 1, "sessions": []})
        else:
            self._read_index()

    def _derive(self, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=SHA256(),
            length=32,
            salt=salt,
            iterations=_ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(self._passphrase.encode("utf-8")))

    def _encode(self, payload: dict[str, Any]) -> str:
        salt = os.urandom(16)
        token = Fernet(self._derive(salt)).encrypt(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        return "\n".join(
            (_MAGIC, base64.b64encode(salt).decode("ascii"), token.decode("ascii"))
        )

    def _decode(self, raw: str) -> dict[str, Any]:
        try:
            magic, encoded_salt, token = raw.strip().splitlines()[:3]
            if magic != _MAGIC:
                raise HistoryError("unsupported history format")
            salt = base64.b64decode(encoded_salt)
            clear = Fernet(self._derive(salt)).decrypt(token.encode("ascii"))
            value = json.loads(clear.decode("utf-8"))
            if not isinstance(value, dict):
                raise HistoryError("history payload is not an object")
            return value
        except InvalidToken as exc:
            raise HistoryError("wrong vault passphrase for conversation history") from exc
        except (ValueError, json.JSONDecodeError, TypeError) as exc:
            raise HistoryError("conversation history is corrupt") from exc

    def _write_encrypted(self, path: Path, payload: dict[str, Any]) -> None:
        temp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(self._encode(payload), encoding="utf-8")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def _read_encrypted(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise HistoryError(f"conversation does not exist: {path.stem}")
        return self._decode(path.read_text(encoding="utf-8"))

    def _read_index(self) -> dict[str, Any]:
        value = self._read_encrypted(self._index_path)
        value.setdefault("version", 1)
        value.setdefault("sessions", [])
        return value

    def _write_index(self, value: dict[str, Any]) -> None:
        self._write_encrypted(self._index_path, value)

    def _path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")
        if not safe or safe != session_id:
            raise HistoryError("invalid conversation id")
        return self.directory / f"{safe}.forge3"

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = list(self._read_index().get("sessions", []))
        sessions.sort(key=lambda item: float(item.get("updated_at", 0)), reverse=True)
        return sessions

    def create_session(self, title: str = "New chat") -> str:
        session_id = uuid.uuid4().hex
        now = time.time()
        payload = {
            "version": 1,
            "id": session_id,
            "title": title.strip() or "New chat",
            "created_at": now,
            "updated_at": now,
            "chat": [],
            "draft": [],
            "anvil": [],
            "anvil_reports": [],
            "last_draft": None,
            "last_goal": None,
            "draft_version": 0,
        }
        self._write_encrypted(self._path(session_id), payload)
        index = self._read_index()
        index["sessions"].append(self._metadata(payload))
        self._write_index(index)
        return session_id

    def _metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        turns = _primary_turns(payload)
        return {
            "id": payload["id"],
            "title": payload.get("title") or "New chat",
            "created_at": float(payload.get("created_at", time.time())),
            "updated_at": float(payload.get("updated_at", time.time())),
            "message_count": len(turns),
            "preview": _preview_text(turns),
        }

    def load_session(self, session_id: str) -> dict[str, Any]:
        return self._read_encrypted(self._path(session_id))

    def save_session(self, session_id: str, content: dict[str, Any]) -> None:
        try:
            current = self.load_session(session_id)
        except HistoryError:
            current = {
                "version": 1,
                "id": session_id,
                "title": "New chat",
                "created_at": time.time(),
            }
        current.update(content)
        current["id"] = session_id
        current["updated_at"] = time.time()
        if (current.get("title") or "New chat") == "New chat":
            title = _first_user_title(_primary_turns(current))
            if title:
                current["title"] = title
        self._write_encrypted(self._path(session_id), current)
        index = self._read_index()
        metadata = self._metadata(current)
        sessions = [
            item for item in index.get("sessions", []) if item.get("id") != session_id
        ]
        sessions.append(metadata)
        index["sessions"] = sessions
        self._write_index(index)

    def rename_session(self, session_id: str, title: str) -> None:
        title = title.strip()
        if not title:
            raise HistoryError("conversation title cannot be empty")
        payload = self.load_session(session_id)
        payload["title"] = title[:100]
        self.save_session(session_id, payload)

    def delete_session(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)
        index = self._read_index()
        index["sessions"] = [
            item for item in index.get("sessions", []) if item.get("id") != session_id
        ]
        self._write_index(index)
