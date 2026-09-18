"""
vault — the one place a secret prompt is allowed to exist.

Every sensitive string in FORGE 3.0 (the FORGE 3.0 persona prompt, the Forge drafting
profile, seed sequences) is resolved through a PromptSource. The rest of the
engine asks a source for a named secret and gets plaintext back — it never knows
or cares whether that plaintext came off local disk or a hosted endpoint.

Two implementations, one interface:

  LocalVault  — model A (passphrase gate). All secrets live in a single sealed
                file: PBKDF2(SHA256, 600k) over a passphrase, Fernet over the
                blob. Decrypted once, held in memory, never written back in the
                clear. Protects the prompt at rest and against anyone without
                the passphrase. Does NOT protect it from someone who has the
                passphrase and runs the tool (local decryption is always
                recoverable in flight) — that's the known ceiling of model A.

  RemoteVault — model B (hosted prompt). The secret never reaches the client;
                the client sends a request to a backend that holds the prompt.
                Stubbed here with the same shape so it can slot in later without
                the engine changing. True secrecy-from-the-user, at the cost of
                running infrastructure.

Nothing here writes a decrypted secret to disk.
"""

from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_KDF_ITERS = 600_000
_MAGIC = "FORGE3-VAULT-1"


class VaultError(Exception):
    """Sealing/opening failed (bad passphrase, corrupt blob, missing secret)."""


# ───────────────────────────────────────────────────────────────────────
# key derivation + low-level seal/unseal — shared by tools and LocalVault
# ───────────────────────────────────────────────────────────────────────

def _derive(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=_KDF_ITERS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def seal(secrets: dict[str, str], passphrase: str) -> str:
    """Seal a {name: plaintext} map into one portable vault blob (text).

    Layout (three lines): magic · base64(salt) · fernet token over the JSON map.
    """
    if not passphrase:
        raise VaultError("refusing to seal with an empty passphrase")
    salt = os.urandom(16)
    key = _derive(passphrase, salt)
    payload = json.dumps(secrets, ensure_ascii=False).encode("utf-8")
    token = Fernet(key).encrypt(payload).decode("ascii")
    return "\n".join((_MAGIC, base64.b64encode(salt).decode("ascii"), token))


def unseal(blob: str, passphrase: str) -> dict[str, str]:
    """Reverse of seal(). Raises VaultError on a wrong passphrase or corruption."""
    try:
        magic, b64salt, token = blob.strip().splitlines()[:3]
    except ValueError as e:
        raise VaultError("vault blob is malformed") from e
    if magic.strip() != _MAGIC:
        raise VaultError("not an FORGE 3.0 vault (bad magic)")
    key = _derive(passphrase, base64.b64decode(b64salt))
    try:
        payload = Fernet(key).decrypt(token.encode("ascii"))
    except InvalidToken as e:
        raise VaultError("wrong passphrase or corrupt vault") from e
    return json.loads(payload.decode("utf-8"))


# ───────────────────────────────────────────────────────────────────────
# the interface the engine talks to
# ───────────────────────────────────────────────────────────────────────

class PromptSource(ABC):
    """Resolve a named secret to plaintext. The engine only ever sees this."""

    @abstractmethod
    def get(self, name: str) -> str: ...

    @abstractmethod
    def names(self) -> list[str]: ...

    def has(self, name: str) -> bool:
        return name in self.names()


# ───────────────────────────────────────────────────────────────────────
# model A — local sealed file, decrypted once into memory
# ───────────────────────────────────────────────────────────────────────

class LocalVault(PromptSource):
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets  # in-memory only

    @classmethod
    def open(cls, path: str | Path, passphrase: str) -> "LocalVault":
        p = Path(path)
        if not p.is_file():
            raise VaultError(f"no vault at {p}")
        return cls(unseal(p.read_text(encoding="utf-8"), passphrase))

    def get(self, name: str) -> str:
        try:
            return self._secrets[name]
        except KeyError as e:
            raise VaultError(f"vault has no secret named {name!r}") from e

    def names(self) -> list[str]:
        return sorted(self._secrets)


# ───────────────────────────────────────────────────────────────────────
# model B — hosted prompt, never lands on the client. shape-only for now.
# ───────────────────────────────────────────────────────────────────────

class RemoteVault(PromptSource):
    """The prompt lives on a server you host; the client never receives it.

    Wired later. Kept here so switching secrecy models is a one-line swap at
    startup and nothing downstream changes.
    """

    def __init__(self, base_url: str, token: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def get(self, name: str) -> str:
        raise NotImplementedError(
            "RemoteVault (hosted-prompt model B) is not wired yet — use LocalVault. "
            "When built, the prompt stays server-side and is never returned to the client."
        )

    def names(self) -> list[str]:
        raise NotImplementedError("RemoteVault is not wired yet")


# ───────────────────────────────────────────────────────────────────────
# canonical secret names the engine looks up
# ───────────────────────────────────────────────────────────────────────

PERSONA = "assistant.persona"       # the FORGE 3.0 system prompt (chat)
PERSONA_ANTHROPIC = "assistant.persona.anthropic"  # compact Claude/Fable identity
DRAFTER = "forge.profile"      # the Forge drafting profile
