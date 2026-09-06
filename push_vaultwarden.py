#!/usr/bin/env python3
"""Push vaultwarden plugin to GitHub repo.

Reads GITHUB_TOKEN from /opt/data/.env and pushes the staged
hermes-vaultwarden-plugin files via the GitHub API.
"""

import json
import os
import subprocess
import urllib.request

VPLUGIN_DIR = "/opt/data/vaultwarden-plugin"


def load_token():
    """Load GITHUB_TOKEN from .env file."""
    with open("/opt/data/.env") as f:
        for line in f:
            if line.startswith("GITHUB_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("GITHUB_TOKEN not found in /opt/data/.env")


def api_request(url, token, method="GET", payload=None):
    """Make an authenticated GitHub API request."""
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def create_repo(token):
    """Create the GitHub repo if it doesn't exist."""
    try:
        result = api_request(
            "https://api.github.com/user/repos",
            token,
            method="POST",
            payload={
                "name": "hermes-vaultwarden-plugin",
                "description": "Vaultwarden secret source plugin for Hermes Agent (SecretSource ABC)",
                "private": False,
                "auto_init": False,
                "has_issues": True,
                "has_wiki": False,
                "has_projects": False,
            },
        )
        print(f"Created: {result.get('html_url')}")
        return result.get("clone_url")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 422:
            print("Repo already exists on account — using existing")
            return "https://github.com/Redenrik/hermes-vaultwarden-plugin.git"
        print(f"Failed: HTTP {e.code}")
        print(body)
        raise


def push_branch(token, clone_url):
    """Push the branch with credential in URL."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    # Set remote with token embedded
    remote_url = clone_url.replace("https://", f"https://{token}@")
    subprocess.run(
        ["git", "remote", "set-url", "origin", remote_url],
        cwd=VPLUGIN_DIR,
        env=env,
        check=True,
    )

    result = subprocess.run(
        ["git", "push", "-u", "origin", "master"],
        cwd=VPLUGIN_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Push failed: {result.stderr}")
        raise RuntimeError("Push failed")
    print("Push successful")
    print(result.stdout)


def main():
    token = load_token()
    print(f"Token prefix: {token[:8]}... len={len(token)}")

    # Verify auth
    user = api_request("https://api.github.com/user", token)
    print(f"Auth OK: {user.get('login')} (id={user.get('id')})")

    # Create repo
    clone_url = create_repo(token)

    # Push
    push_branch(token, clone_url)

    print("\nAll done! Repo: https://github.com/Redenrik/hermes-vaultwarden-plugin")


if __name__ == "__main__":
    main()