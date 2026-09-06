"""Vaultwarden secret source plugin for Hermes Agent.

Pulls credentials from a Vaultwarden/Bitwarden-compatible server via its
REST API. Scoped by collection — never dumps the whole vault unless
explicitly configured.

Usage:
    from hermes_tools import secret_source
    ctx.register_secret_source(VaultwardenSource)
"""

import json
import os
import urllib.request
import urllib.error
import ssl as _ssl
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ErrorKind(Enum):
    CONFIG_ERROR = "CONFIG_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    UNKNOWN = "UNKNOWN"


@dataclass
class FetchResult:
    secrets: dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    error_kind: Optional[ErrorKind] = None
    override_existing: bool = False


# --- Vaultwarden API client ---

DEFAULT_SERVER = "https://vaultwarden.red-nas.local:30022"


def _ssl_context() -> _ssl.SSLContext:
    """Create SSL context for Vaultwarden mkcert dev cert (local testing only)."""
    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE
    return ctx


def _request_json(url: str, token: str, timeout: int = 10) -> dict:
    """Make a bearer-token authenticated request to Vaultwarden API."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    ctx = _ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode())


def _strip_vw_prefix(ref: str) -> str:
    """Strip vw:// prefix from a mapped reference."""
    if ref.startswith("vw://"):
        return ref[5:]
    return ref


def scope_collection(ciphers: list[dict], allowed_names: set[str]) -> list[dict]:
    """Filter ciphers to only those in allowed collection names."""
    return [c for c in ciphers if c.get("name", "") in allowed_names]


# --- SecretSource ABC implementation ---

def fetch(cfg: dict, home_path: str) -> FetchResult:
    """Fetch secrets from Vaultwarden.

    Args:
        cfg: dict with server_url, token, collection_id, collection_refs, override_existing
        home_path: Hermes home path (not used — Vaultwarden is network-based)

    Returns:
        FetchResult with secrets dict or error info.
    """
    server_url = cfg.get("server_url", DEFAULT_SERVER)
    token = cfg.get("token") or os.environ.get("VAULTWARDEN_TOKEN", "")
    collection_id = cfg.get("collection_id", "")
    collection_refs = cfg.get("collection_refs", [])
    override_existing = cfg.get("override_existing", False)

    if not token:
        return FetchResult(
            error="No token configured — set VAULTWARDEN_TOKEN or token in config",
            error_kind=ErrorKind.CONFIG_ERROR,
            override_existing=override_existing,
        )

    try:
        # Fetch collections to map collection_id to UUID
        collections = _request_json(f"{server_url.rstrip('/')}/api/collections", token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return FetchResult(
                error=f"Authentication failed (HTTP {e.code}) — check token",
                error_kind=ErrorKind.AUTH_ERROR,
                override_existing=override_existing,
            )
        return FetchResult(
            error=f"HTTP {e.code} from collections endpoint",
            error_kind=ErrorKind.NETWORK_ERROR,
            override_existing=override_existing,
        )
    except urllib.error.URLError as e:
        return FetchResult(
            error=f"Network error: {e.reason}",
            error_kind=ErrorKind.NETWORK_ERROR,
            override_existing=override_existing,
        )
    except Exception as e:
        return FetchResult(
            error=f"Unexpected error: {e}",
            error_kind=ErrorKind.UNKNOWN,
            override_existing=override_existing,
        )

    # If collection_refs provided, fetch only those
    if collection_refs:
        ciphers = []
        for ref in collection_refs:
            uuid = _strip_vw_prefix(ref)
            try:
                c = _request_json(f"{server_url.rstrip('/')}/api/collections/{uuid}", token)
                ciphers.extend(c.get("data", []))
            except urllib.error.HTTPError:
                continue
    elif collection_id:
        # Fetch by collection ID
        try:
            ciphers = _request_json(
                f"{server_url.rstrip('/')}/api/collections/{collection_id}", token
            )
            ciphers = ciphers.get("data", [])
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return FetchResult(
                    error=f"Collection {collection_id} not found",
                    error_kind=ErrorKind.NOT_FOUND,
                    override_existing=override_existing,
                )
            return FetchResult(
                error=f"HTTP {e.code} from collection endpoint",
                error_kind=ErrorKind.NETWORK_ERROR,
                override_existing=override_existing,
            )
    else:
        # No scope — return empty (safety default, never dump whole vault)
        return FetchResult(
            secrets={},
            error=None,
            error_kind=None,
            override_existing=override_existing,
        )

    # Extract KEY=VALUE pairs from ciphers
    secrets = {}
    for cipher in ciphers:
        name = cipher.get("name", "unnamed")
        login = cipher.get("login", {})
        username = login.get("username", "")
        password = login.get("password", "")
        if username:
            secrets[f"{name}_USERNAME"] = username
        if password:
            secrets[f"{name}_PASSWORD"] = password

    return FetchResult(
        secrets=secrets,
        error=None,
        error_kind=None,
        override_existing=override_existing,
    )


def register(ctx) -> None:
    """Register this source with the Hermes secret framework."""
    from hermes_tools import secret_source
    secret_source.register(VaultwardenSource)


class VaultwardenSource:
    """Wrapper class for the SecretSource ABC."""
    fetch = staticmethod(fetch)
    register = staticmethod(register)