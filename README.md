# hermes-vaultwarden-plugin

Vaultwarden secret source plugin for **Hermes Agent** — pulls credentials from
a Vaultwarden/Bitwarden-compatible server at Hermes startup and exposes full
CRUD operations (store, retrieve, update, delete, search) as runtime Hermes
tools.

## What it is

A Hermes Agent plugin that implements the `SecretSource` ABC contract
(`agent/secret_sources/base.py`). On startup it authenticates with a
Vaultwarden instance via the Client API (`client_credentials` grant), fetches
the configured ciphers/collections, and injects them into the environment as
Hermes profile secrets. At runtime, the included Hermes tool bridge exposes
six tools on the `vaultwarden` toolset for credential lifecycle management.

## Components

| File | Role |
|------|------|
| `plugins/vaultwarden/__init__.py` | Secret source: auth, fetch, store, retrieve, update, delete, search |
| `plugins/vaultwarden/plugin.yaml` | Plugin metadata + defaults (server URL, token env, collections) |
| `plugins/vaultwarden/tests_conformance.py` | Conformance tests against the `SecretSource` contract (10 cases) |
| `tools/vaultwarden_tools.py` | Hermes tool bridge: 6 tools on the `vaultwarden` toolset |

## How it works

### Startup (read)

1. Hermes reads `secrets.vaultwarden` from `config.yaml`
2. The plugin authenticates to Vaultwarden via `POST /identity/connect/token` with
   `client_id` + `client_secret` (or falls back to a pre-existing `VAULTWARDEN_TOKEN`)
3. Fetches ciphers by UUID (`cipher_refs`) and/or collections (`collection_refs`)
4. Injects secrets into `os.environ` for the Hermes session

### Runtime (write)

The six tools on the `vaultwarden` toolset let Hermes store, retrieve, update,
delete, and search credentials while handling a task:

| Tool | What it does |
|------|-------------|
| `vaultwarden_status` | Check server reachability and auth state |
| `vaultwarden_store` | Create a new credential (login, card, identity, secure_note, document) |
| `vaultwarden_retrieve` | Read a credential by UUID |
| `vaultwarden_update` | Partially update an existing credential |
| `vaultwarden_delete` | Archive (soft-delete) a credential |
| `vaultwarden_search` | Search by name/username, with optional type filter |

All tools accept a pre-authenticated session token and skip re-authentication on
every call — matching real Hermes runtime behavior (one auth per session, token
reused across tool dispatches).

## Configuration

Edit `plugins/vaultwarden/plugin.yaml` (or set equivalent values in
`secrets.vaultwarden` in your `config.yaml`):

```yaml
secrets:
  vaultwarden:
    enabled: true
    server_url: "https://your-vaultwarden.example.com:30022"
    client_id: "user.00000000-0000-0000-0000-000000000000"
    client_secret: "your-api-key"
    # Optional
    cipher_refs: ""            # pipe-separated UUIDs for mapped mode
    collection_refs: ""        # comma-separated collection UUIDs for bulk mode
    scope_collection: ""       # restrict fetches to this collection
    override_existing: false   # local vault = personal; .env wins by default
    allow_write: true          # enable store/update/delete at runtime
    write_collection: ""       # collection to place new items in (empty = user vault)
    timeout_seconds: 30.0
```

### Getting the client_id / client_secret

In Vaultwarden web UI: go to Admin page → API Keys → create a new key. The
`client_id` is your user UUID (`user.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`),
the `client_secret` is the generated key. Both are required for the
`client_credentials` auth flow.

### Token environment variable

Alternatively, set `VAULTWARDEN_TOKEN` in your environment to a pre-existing
Vaultwarden session token. This bypasses the `client_credentials` flow and is
useful when you already have a valid token (e.g. from a previous login).

## DNS and TLS in containers

Docker containers don't inherit the host's `/etc/hosts`. If your Vaultwarden
runs on the host network with a custom hostname, the plugin includes a
`DNS_OVERRIDE` mapping (hostname → IP) and uses SNI-aware TLS via
`ssl.wrap_socket(server_hostname=...)` to connect through mkcert dev certs.
Adjust `DNS_OVERRIDE` in `__init__.py` if your setup differs.

## Projects that use this

This plugin was developed for **Hermes Agent on TrueNAS** (RED-NAS), with the
Vaultwarden instance running on the same host at `vaultwarden.red-nas.local:30022`.
The server URL, DNS override, and TLS settings are configured for that
environment — adjust for your own setup.

## Development

### Running conformance tests

```bash
cd plugins/vaultwarden
python3 tests_conformance.py
```

Requires Python 3.13+, no pip dependencies. The tests use unittest and mock
HTTP responses — they don't touch a real Vaultwarden server.

### End-to-end verification

The real test is against a live Vaultwarden instance. The plugin's CRUD methods
have been verified against `https://vaultwarden.red-nas.local:30022` with a
full create→read→update→search→delete cycle. See the simulation script for a
replayable end-to-end test.

### Requirements

- Python 3.13+ (stdlib only — no pip dependencies for the plugin itself)
- A Vaultwarden/Bitwarden-compatible server with Client API enabled
- Valid `client_id` / `client_secret` or a session token

## Architecture

The plugin follows the Hermes Agent plugin architecture:

- **`SecretSource` ABC** (`agent/secret_sources/base.py`): defines the contract —
  `fetch(cfg, home_path) → FetchResult`, plus config schema, auth hooks, and
  error kinds. The plugin implements this for read operations.
- **Write operations** are not part of the `SecretSource` contract (by design —
  the ABC is read-only). The plugin adds `store/retrieve/update/delete/search`
  as standalone methods that Hermes tools call directly.
- **Tool registration**: `vaultwarden_tools.py` registers six tools on the
  `vaultwarden` toolset via `tools.registry`. Each tool dispatches to the
  corresponding plugin method with a pre-authenticated token.

## License

MIT — use it, modify it, integrate it. If you extend it and it helps your
Hermes Agent setup, that's the point.

## Author

Built for [Enrico Spangenberg Yanes](https://github.com/Redenrik) on
[RED-NAS](https://github.com/Redenrik) — Hermes Agent TrueNAS instance.

---

*For issues, PRs, and notifications: see the GitHub repo. This plugin is
maintained as part of the RED FLEET Hermes Agent deployment on TrueNAS.*
