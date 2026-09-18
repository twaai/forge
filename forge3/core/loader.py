"""Resolve the sealed FORGE 3.0 prompt source."""

from __future__ import annotations

import os
from getpass import getpass
from pathlib import Path

from . import vault
from .providers import FORGE3_HOME
from .public_defaults import FORGE3_PERSONA, FORGE_PROFILE
from .vault import PromptSource

VAULT_PATH = FORGE3_HOME / "vault.dat"


def find_vault() -> Path | None:
    return VAULT_PATH if VAULT_PATH.is_file() else None


def resolve_source(passphrase: str | None = None) -> tuple[PromptSource, str]:
    """Return the encrypted local vault or the encoded built-in profile."""
    vault_path = find_vault()
    if vault_path:
        password = passphrase or os.getenv("FORGE3_VAULT") or getpass(
            "FORGE 3.0 vault passphrase: "
        )
        return vault.LocalVault.open(vault_path, password), "vault"

    source = vault.LocalVault(
        {
            vault.PERSONA: FORGE3_PERSONA,
            vault.DRAFTER: FORGE_PROFILE,
        }
    )
    return source, "sealed-defaults"
