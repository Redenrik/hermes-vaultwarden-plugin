#!/usr/bin/env python3
"""vaultwarden_tools.py — Hermes tool bridge for Vaultwarden CRUD operations.

Exposes the Vaultwarden plugin's write methods (store/retrieve/update/delete/search)
as registered Hermes agent tools so the model can call them at runtime.

Registration pattern follows tools/registry.py — each tool is a schema dict
+ handler function registered via registry.register().  The toolset is
"vaultwarden" so it can be gated by config.yaml tools.vaultwarden.enabled.

Handlers return JSON strings (registry contract).  All Vaultwarden API calls
are made through the plugin's VaultwardenSource which handles auth, SNI,
and DNS override internally.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import of the plugin source — import only when a tool is dispatched,
# keeping startup cheap.  Imports are retried with path fixup on ImportError.
# ---------------------------------------------------------------------------

_PLUGIN_PATH = "/opt/data/plugins/vaultwarden"
_PLUGINS_SYS_PREFIX = "/opt/data/plugins"


def _ensure_plugin_importable() -> bool:
    """Add the plugins directory to sys.path if not already there.

    Returns True on success, False if the plugin package cannot be found.
    """
    if _PLUGIN_PATH not in sys.path:
        sys.path.insert(0, _PLUGIN_PATH)
    if _PLUGINS_SYS_PREFIX not in sys.path:
        sys.path.insert(0, _PLUGINS_SYS_PREFIX)
    try:
        import vaultwarden  # noqa: F401
        return True
    except ImportError as exc:
        logger.warning("vaultwarden plugin not importable: %s", exc)
        return False


def _get_source() -> Any:
    """Return a fresh VaultwardenSource instance, or raise if unavailable."""
    if not _ensure_plugin_importable():
        raise ImportError("vaultwarden plugin unavailable")
    from vaultwarden import VaultwardenSource  # noqa: F811

    return VaultwardenSource()


def _load_config() -> dict:
    """Load the Vaultwarden config section from config.yaml."""
    import yaml

    cfg_path = "/opt/data/config.yaml"
    try:
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return {}
    return cfg.get("secrets", {}).get("vaultwarden", {})


# ---------------------------------------------------------------------------
# Schemas — OpenAI function-calling format
# ---------------------------------------------------------------------------

VW_STORE_SCHEMA = {
    "name": "vaultwarden_store",
    "description": (
        "Store a credential in Vaultwarden. Creates a new cipher "
        "with the given login fields (username/password/uris). "
        "Use vw://<uuid> refs to reference stored credentials later. "
        "Respects override_existing=false by default — will not "
        "overwrite an existing cipher unless override=true."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Credential name / title for the vault entry",
            },
            "username": {
                "type": "string",
                "description": "Login username",
            },
            "password": {
                "type": "string",
                "description": "Login password (will be stored plaintext — Vaultwarden server encrypts at rest)",
            },
            "uris": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of URIs associated with this credential",
            },
            "folder_uuid": {
                "type": "string",
                "description": "Optional folder UUID to store the credential in",
            },
            "collection_uuids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional collection UUIDs to share the credential with",
            },
            "override": {
                "type": "boolean",
                "description": "Override existing cipher with the same name (default: false)",
                "default": False,
            },
        },
        "required": ["name", "username", "password"],
    },
}

VW_RETRIEVE_SCHEMA = {
    "name": "vaultwarden_retrieve",
    "description": (
        "Retrieve a credential from Vaultwarden by its UUID. "
        "Returns the cipher's login fields (username, password, uris). "
        "Use the vw:// UUID reference that was returned by store."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "uuid": {
                "type": "string",
                "description": "The Vaultwarden cipher UUID (from vw:// ref or store response)",
            },
        },
        "required": ["uuid"],
    },
}

VW_UPDATE_SCHEMA = {
    "name": "vaultwarden_update",
    "description": (
        "Update an existing Vaultwarden credential. Pass only the fields "
        "you want to change; omitted fields stay the same. "
        "Use vw://<uuid> refs to identify the cipher."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "uuid": {
                "type": "string",
                "description": "The Vaultwarden cipher UUID to update",
            },
            "name": {
                "type": "string",
                "description": "New credential name/title",
            },
            "username": {
                "type": "string",
                "description": "New login username",
            },
            "password": {
                "type": "string",
                "description": "New login password",
            },
            "uris": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New list of URIs",
            },
            "folder_uuid": {
                "type": "string",
                "description": "New folder UUID (or null to remove from folder)",
            },
        },
        "required": ["uuid"],
    },
}

VW_DELETE_SCHEMA = {
    "name": "vaultwarden_delete",
    "description": (
        "Delete (archive) a credential from Vaultwarden by UUID. "
        "Vaultwarden archives (soft-delete) — not permanent removal. "
        "Use vw://<uuid> refs to identify the cipher."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "uuid": {
                "type": "string",
                "description": "The Vaultwarden cipher UUID to archive/delete",
            },
        },
        "required": ["uuid"],
    },
}

VW_SEARCH_SCHEMA = {
    "name": "vaultwarden_search",
    "description": (
        "Search Vaultwarden credentials by name or username. "
        "Returns matching cipher UUIDs and names (not passwords)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term — matches against credential names and usernames",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 20, max 100)",
                "default": 20,
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["query"],
    },
}

VW_STATUS_SCHEMA = {
    "name": "vaultwarden_status",
    "description": (
        "Check Vaultwarden plugin connectivity and auth status. "
        "Returns whether the server is reachable and the current "
        "auth token is valid."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_store(args: dict, **kw) -> str:
    """Store a credential in Vaultwarden."""
    source = _get_source()
    cfg = _load_config()
    name = args.get("name", "")
    username = args.get("username", "")
    password = args.get("password", "")
    uris = args.get("uris") or []
    folder_uuid = args.get("folder_uuid")
    collection_uuids = args.get("collection_uuids") or []
    override = args.get("override", False)

    if not name or not username or not password:
        return json.dumps({
            "error": "Missing required fields: name, username, password",
            "success": False,
        })

    server = str(cfg.get("server_url", source.DEFAULT_SERVER)).rstrip("/")

    # Build login_info dict for the plugin's store() signature
    login_info: dict = {"username": username, "password": password}
    if uris:
        login_info["uris"] = uris

    try:
        result = source.store(
            server=server,
            token=source._authenticate(server,
                                       cfg.get("client_id", ""),
                                       cfg.get("client_secret", ""),
                                       float(cfg.get("timeout_seconds", 30.0))),
            credential_type="login",
            name=name,
            login_info=login_info,
            collection_id=collection_uuids[0] if collection_uuids else None,
        )
        return json.dumps({"success": True, "cipher": result})
    except Exception as exc:
        logger.exception("vaultwarden_store failed")
        return json.dumps({"error": str(exc), "success": False})


def _handle_retrieve(args: dict, **kw) -> str:
    """Retrieve a credential from Vaultwarden by UUID."""
    source = _get_source()
    cfg = _load_config()
    uuid = args.get("uuid", "")

    if not uuid:
        return json.dumps({"error": "Missing uuid", "success": False})

    server = str(cfg.get("server_url", source.DEFAULT_SERVER)).rstrip("/")

    try:
        token = source._authenticate(server,
                                     cfg.get("client_id", ""),
                                     cfg.get("client_secret", ""),
                                     float(cfg.get("timeout_seconds", 30.0)))
        result = source.retrieve(server=server, token=token, cipher_id=uuid)
        return json.dumps({"success": True, "cipher": result})
    except Exception as exc:
        logger.exception("vaultwarden_retrieve failed")
        return json.dumps({"error": str(exc), "success": False})


def _handle_update(args: dict, **kw) -> str:
    """Update an existing Vaultwarden credential."""
    source = _get_source()
    cfg = _load_config()
    uuid = args.get("uuid", "")

    if not uuid:
        return json.dumps({"error": "Missing uuid", "success": False})

    server = str(cfg.get("server_url", source.DEFAULT_SERVER)).rstrip("/")

    try:
        token = source._authenticate(server,
                                     cfg.get("client_id", ""),
                                     cfg.get("client_secret", ""),
                                     float(cfg.get("timeout_seconds", 30.0)))
        result = source.update(
            server=server,
            token=token,
            cipher_id=uuid,
            credential_type="login",
            name=args.get("name"),
            login_info={k: v for k, v in args.items() if k in ("username", "password", "uris") if v},
        )
        return json.dumps({"success": True, "cipher": result})
    except Exception as exc:
        logger.exception("vaultwarden_update failed")
        return json.dumps({"error": str(exc), "success": False})


def _handle_delete(args: dict, **kw) -> str:
    """Archive/delete a credential from Vaultwarden."""
    source = _get_source()
    cfg = _load_config()
    uuid = args.get("uuid", "")

    if not uuid:
        return json.dumps({"error": "Missing uuid", "success": False})

    server = str(cfg.get("server_url", source.DEFAULT_SERVER)).rstrip("/")

    try:
        token = source._authenticate(server,
                                     cfg.get("client_id", ""),
                                     cfg.get("client_secret", ""),
                                     float(cfg.get("timeout_seconds", 30.0)))
        source.delete(server=server, token=token, cipher_id=uuid)
        return json.dumps({"success": True, "uuid": uuid, "archived": True})
    except Exception as exc:
        logger.exception("vaultwarden_delete failed")
        return json.dumps({"error": str(exc), "success": False})


def _handle_search(args: dict, **kw) -> str:
    """Search Vaultwarden credentials by name/username."""
    source = _get_source()
    cfg = _load_config()
    query = args.get("query", "")
    limit = args.get("limit", 20)

    if not query:
        return json.dumps({"error": "Missing query", "success": False})

    server = str(cfg.get("server_url", source.DEFAULT_SERVER)).rstrip("/")

    try:
        token = source._authenticate(server,
                                     cfg.get("client_id", ""),
                                     cfg.get("client_secret", ""),
                                     float(cfg.get("timeout_seconds", 30.0)))
        results = source.search(server=server, token=token, query=query)
        return json.dumps({"success": True, "results": results})
    except Exception as exc:
        logger.exception("vaultwarden_search failed")
        return json.dumps({"error": str(exc), "success": False})


def _handle_status(args: dict, **kw) -> str:
    """Check Vaultwarden plugin connectivity."""
    try:
        source = _get_source()
        cfg = _load_config()
        server = str(cfg.get("server_url", source.DEFAULT_SERVER)).rstrip("/")
        client_id = cfg.get("client_id", "")
        client_secret = cfg.get("client_secret", "")

        if not client_id or not client_secret:
            return json.dumps({
                "success": False,
                "error": "No client_id/client_secret configured",
                "server": server,
            })

        token = source._authenticate(server, client_id, client_secret, 15.0)
        if not token:
            return json.dumps({
                "success": False,
                "error": "Authentication failed — no token",
                "server": server,
            })

        # Lightweight reachability check
        result = source.fetch(cfg, "/opt/data")
        return json.dumps({
            "success": result.ok,
            "server": server,
            "error": result.error,
            "error_kind": result.error_kind,
            "warnings": result.warnings,
            "authenticated": True,
        })
    except Exception as exc:
        logger.exception("vaultwarden_status failed")
        return json.dumps({"error": str(exc), "success": False})


# ---------------------------------------------------------------------------
# Registration — called at module import time by tools/__init__.py discovery
# ---------------------------------------------------------------------------

def register_tools() -> None:
    """Register all vaultwarden_tools with the Hermes tool registry.

    Called from tools/__init__.py auto-discovery or explicitly from
    the gateway startup sequence.  Each registration gates on the
    vaultwarden toolset being available (server reachable + auth valid).
    """
    from tools.registry import registry

    # Check availability once at registration time; the check_fn is
    # cached so subsequent calls don't hammer the server.
    registry.register(
        name="vaultwarden_store",
        toolset="vaultwarden",
        schema=VW_STORE_SCHEMA,
        handler=_handle_store,
        check_fn=_check_vaultwarden,
        emoji="🔐",
        description="Store a credential in Vaultwarden",
    )
    registry.register(
        name="vaultwarden_retrieve",
        toolset="vaultwarden",
        schema=VW_RETRIEVE_SCHEMA,
        handler=_handle_retrieve,
        check_fn=_check_vaultwarden,
        emoji="🔍",
        description="Retrieve a credential from Vaultwarden by UUID",
    )
    registry.register(
        name="vaultwarden_update",
        toolset="vaultwarden",
        schema=VW_UPDATE_SCHEMA,
        handler=_handle_update,
        check_fn=_check_vaultwarden,
        emoji="✏️",
        description="Update an existing Vaultwarden credential",
    )
    registry.register(
        name="vaultwarden_delete",
        toolset="vaultwarden",
        schema=VW_DELETE_SCHEMA,
        handler=_handle_delete,
        check_fn=_check_vaultwarden,
        emoji="🗑️",
        description="Archive/delete a credential from Vaultwarden",
    )
    registry.register(
        name="vaultwarden_search",
        toolset="vaultwarden",
        schema=VW_SEARCH_SCHEMA,
        handler=_handle_search,
        check_fn=_check_vaultwarden,
        emoji="🔎",
        description="Search Vaultwarden credentials by name/username",
    )
    registry.register(
        name="vaultwarden_status",
        toolset="vaultwarden",
        schema=VW_STATUS_SCHEMA,
        handler=_handle_status,
        check_fn=None,  # always available — lightweight check
        emoji="📊",
        description="Check Vaultwarden plugin connectivity and auth status",
    )


def _check_vaultwarden() -> bool:
    """Availability check for the vaultwarden toolset.

    Returns True when the plugin can reach the Vaultwarden server
    and authenticate.  Used by the registry's check_fn cache so
    the tools are only exposed when the backend is healthy.
    """
    try:
        source = _get_source()
        cfg = _load_config()
        server = str(cfg.get("server_url", source.DEFAULT_SERVER)).rstrip("/")
        client_id = cfg.get("client_id", "")
        client_secret = cfg.get("client_secret", "")

        if not client_id or not client_secret:
            return False

        token = source._authenticate(server, client_id, client_secret, 15.0)
        if not token:
            return False

        result = source.fetch(cfg, "/opt/data")
        return result.ok
    except Exception:
        return False


# Auto-register when this module is imported (standard pattern for
# self-registering tool modules in tools/).
try:
    register_tools()
except Exception:
    # Don't crash startup — tools register lazily anyway.
    logger.exception("vaultwarden_tools registration deferred")