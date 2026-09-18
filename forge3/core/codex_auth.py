"""Local Codex CLI login — ChatGPT subscription auth on this machine.

Reads `~/.codex/auth.json` (or $CODEX_HOME/auth.json) written by `codex login`.
Tokens stay on disk. Callers get a short-lived access token, never a log line.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

# Public Codex CLI OAuth client. Same id the official CLI uses to refresh.
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_TOKEN_URL = "https://auth.openai.com/oauth/token"


class CodexAuthError(RuntimeError):
    pass


def auth_path() -> Path:
    home = os.environ.get("CODEX_HOME", "").strip()
    root = Path(home).expanduser() if home else Path.home() / ".codex"
    return root / "auth.json"


def available() -> bool:
    try:
        data = _read()
    except CodexAuthError:
        return False
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    return bool(str(tokens.get("access_token") or "").strip() or str(tokens.get("refresh_token") or "").strip())


def _read() -> dict[str, Any]:
    path = auth_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CodexAuthError("no Codex login on this machine — run `codex login`") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodexAuthError("Codex auth.json is corrupt") from exc
    if not isinstance(data, dict):
        raise CodexAuthError("Codex auth.json is not an object")
    return data


def _write(data: dict[str, Any]) -> None:
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _jwt_exp(token: str) -> int | None:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return int(data["exp"])
    except Exception:
        return None


def _fresh(access: str) -> bool:
    exp = _jwt_exp(access)
    if exp is None:
        return bool(access)
    return exp > int(time.time()) + 60


def session() -> tuple[str, str]:
    """Return (access_token, account_id), refreshing if the access token is stale."""
    data = _read()
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    access = str(tokens.get("access_token") or "").strip()
    refresh = str(tokens.get("refresh_token") or "").strip()
    account = str(tokens.get("account_id") or "").strip()
    if not account:
        raise CodexAuthError("Codex login is missing an account id — run `codex login` again")
    if access and _fresh(access):
        return access, account
    if not refresh:
        raise CodexAuthError("Codex login expired — run `codex login`")
    access, refresh, account = _refresh(refresh, account)
    tokens["access_token"] = access
    tokens["refresh_token"] = refresh
    tokens["account_id"] = account
    data["tokens"] = tokens
    data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write(data)
    return access, account


def _refresh(refresh_token: str, account_id: str) -> tuple[str, str, str]:
    import httpx

    try:
        response = httpx.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": _CLIENT_ID,
            },
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise CodexAuthError("Codex token refresh failed") from exc
    if response.status_code >= 400:
        raise CodexAuthError("Codex login expired — run `codex login`")
    try:
        payload = response.json()
    except ValueError as exc:
        raise CodexAuthError("Codex token refresh returned non-JSON") from exc
    access = str(payload.get("access_token") or "").strip()
    new_refresh = str(payload.get("refresh_token") or refresh_token).strip()
    if not access:
        raise CodexAuthError("Codex token refresh returned no access token")
    return access, new_refresh, account_id
