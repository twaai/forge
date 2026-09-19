"""Shared HTTPS transport policy for every remote Forge provider."""

from __future__ import annotations

import ssl
from typing import Any

import httpx
import truststore


CONNECT_RETRIES = 4
CONNECT_TIMEOUT_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 180.0


def system_tls_verifier(verify: bool) -> Any:
    """Return an OS-backed TLS context, or False for explicit proxy mode."""
    if not verify:
        return False
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def provider_http_client(
    verify: bool,
    *,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> httpx.Client:
    """Create the transport shared by API, OAuth, catalog, and stream calls."""
    verifier = system_tls_verifier(verify)
    transport = httpx.HTTPTransport(verify=verifier, retries=CONNECT_RETRIES)
    return httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT_SECONDS),
        follow_redirects=True,
    )
