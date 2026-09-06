#!/usr/bin/env python3
"""Push vaultwarden plugin to GitHub repo.

Reads GITHUB_TOKEN from /opt/data/.env and pushes the staged
hermes-vaultwarden-plugin files via the GitHub API.
"""

import json
import urllib.request
import urllib.error
import os
from pathlib import Path

ENV_PATH = Path('/opt/data/.env')
GITHUB_REPO = 'Redenrik/hermes-vaultwarden-plugin'
PLUGIN_DIR = Path(__file__).parent


def load_github_token():
    """Load GITHUB_TOKEN from /opt/data/.env"""
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith('GITHUB_TOKEN='):
            return line.split('=', 1)[1].strip()
    return None


def gh_api(method, path, token, body=None):
    """Make authenticated GitHub API request"""
    url = f'https://api.github.com{path}'
    req = urllib.request.Request(url, method=method)
    req.add_header('Authorization', f'token {token}')
    req.add_header('Accept', 'application/vnd.github.v3+json')
    req.add_header('User-Agent', 'hermes-push-script')
    if body:
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f'GitHub API error: {e.code} {e.reason}')
        return None


def push_file(path, token, message):
    """Push a single file via GitHub API"""
    rel = str(path.relative_to(PLUGIN_DIR))
    content = path.read_bytes()
    import base64
    encoded = base64.b64encode(content).decode('ascii')
    
    # Get existing SHA if file exists
    existing = gh_api('GET', f'/repos/{GITHUB_REPO}/contents/{rel}', token)
    sha = existing.get('sha') if existing else None
    
    body = {
        'message': message,
        'content': encoded,
        'branch': 'master'
    }
    if sha:
        body['sha'] = sha
    
    result = gh_api('PUT', f'/repos/{GITHUB_REPO}/contents/{rel}', token, body)
    return result


def main():
    token = load_github_token()
    if not token:
        print('ERROR: GITHUB_TOKEN not found in /opt/data/.env')
        return 1
    
    print(f'Token prefix: {token[:8]}... len={len(token)}')
    
    # Verify auth
    user = gh_api('GET', '/user', token)
    if not user:
        print('Auth failed')
        return 1
    print(f'Auth OK: {user.get("login")} (id={user.get("id")})')
    
    # Check repo
    repo = gh_api('GET', f'/repos/{GITHUB_REPO}', token)
    if not repo:
        print(f'Repo {GITHUB_REPO} not found or no access')
        return 1
    print(f'Repo exists: {repo.get("full_name")}')
    
    # Push files
    files = ['__init__.py', 'plugin.yaml', 'tests_conformance.py']
    for fname in files:
        fpath = PLUGIN_DIR / fname
        if not fpath.exists():
            print(f'Skipping {fname} - not found')
            continue
        result = push_file(fpath, token, f'update {fname}')
        if result:
            print(f'Pushed {fname}')
        else:
            print(f'Failed to push {fname}')
    
    print(f'All done! Repo: https://github.com/{GITHUB_REPO}')
    return 0


if __name__ == '__main__':
    exit(main())