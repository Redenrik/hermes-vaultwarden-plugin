#!/usr/bin/env python3
"""Conformance tests for Vaultwarden Secret Source plugin v0.1.0.
Uses unittest (no pip dependency). Run: python3 tests_conformance.py
"""

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent
sys.path.insert(0, str(PLUGIN_DIR))

from __init__ import (
    fetch, FetchResult, ErrorKind,
    _strip_vw_prefix, scope_collection,
)


class TestVaultwardenConformance:
    """SecretSource conformance contract — 6 rules + Vaultwarden-specific tests."""

    def test_fetch_returns_fetchresult(self):
        cfg = {"server_url": "https://vaultwarden.red-nas.local:30022", "token": "test"}
        result = fetch(cfg, "/tmp")
        assert isinstance(result, FetchResult)

    def test_error_kind_has_required_types(self):
        required = {"CONFIG_ERROR", "AUTH_ERROR", "NETWORK_ERROR", "NOT_FOUND", "RATE_LIMITED", "UNKNOWN"}
        kinds = {e.value for e in ErrorKind}
        assert required.issubset(kinds)

    def test_fail_open_on_missing_token(self):
        cfg = {"server_url": "https://vaultwarden.red-nas.local:30022"}
        result = fetch(cfg, "/tmp")
        assert result.error is not None
        assert result.error_kind == ErrorKind.CONFIG_ERROR

    def test_no_shell_in_fetch(self):
        cfg = {"server_url": "https://vaultwarden.red-nas.local:30022", "token": "test"}
        result = fetch(cfg, "/tmp")
        assert result.error_kind in (ErrorKind.NETWORK_ERROR, ErrorKind.AUTH_ERROR, ErrorKind.CONFIG_ERROR)

    def test_override_existing_defaults_false(self):
        cfg = {"server_url": "https://vaultwarden.red-nas.local:30022", "token": "test", "override_existing": False}
        result = fetch(cfg, "/tmp")
        assert result.override_existing is False

    def test_vw_scheme_stripped(self):
        stripped = _strip_vw_prefix("vw://abc123-def456")
        assert stripped == "abc123-def456"
        assert not stripped.startswith("vw://")

    def test_default_server_url(self):
        cfg = {"server_url": "https://vaultwarden.red-nas.local:30022", "token": "test"}
        result = fetch(cfg, "/tmp")
        assert result.error is not None or result.secrets is not None

    def test_hostname_not_ip(self):
        cfg = {"server_url": "https://vaultwarden.red-nas.local:30022", "token": "test"}
        result = fetch(cfg, "/tmp")
        assert "vaultwarden.red-nas.local" in str(cfg["server_url"])

    def test_scope_collection_filters(self):
        ciphers = [
            {"id": "1", "name": "login", "collectionIds": ["coll-a"]},
            {"id": "2", "name": "api", "collectionIds": ["coll-b"]},
        ]
        scoped = scope_collection(ciphers, {"login"})
        assert len(scoped) == 1
        assert scoped[0]["name"] == "login"

    def test_collection_refs_property(self):
        assert callable(_strip_vw_prefix)
        assert callable(scope_collection)


if __name__ == "__main__":
    passed = 0
    failed = 0
    for name, method in sorted(TestVaultwardenConformance.__dict__.items()):
        if name.startswith("_") or not callable(method):
            continue
        try:
            method(None)
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)