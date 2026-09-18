"""FORGE 3.0 prompt defaults decoded only at runtime."""

from .sealed_prompts import reveal

FORGE3_PERSONA: str = reveal("FORGE3_PERSONA")
FORGE_PROFILE: str = reveal("FORGE_PROFILE")
