#!/usr/bin/env python3
from __future__ import annotations

import requests


def _post_json(url: str, token: str, payload: dict, timeout: int = 15) -> requests.Response:
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return requests.post(url, headers=headers, json=payload, timeout=timeout)


def ensure_mirror(base_url: str, token: str, upstream: str, owner: str, repo: str) -> tuple[bool, str | None]:
    """Best-effort: ensure a Gitea pull mirror exists for upstream under owner/repo.

    Uses the migrate API with mirror=True. Returns (ok, error_message).
    """
    url = base_url.rstrip("/") + "/api/v1/repos/migrate"
    payload = {
        "clone_addr": upstream,
        "repo_name": repo,
        "repo_owner": owner,
        "mirror": True,
        "private": False,
    }
    try:
        r = _post_json(url, token, payload)
        if r.status_code in (200, 201, 409):  # 409 = already exists
            return True, None
        return False, f"HTTP {r.status_code}: {r.text.strip()}"
    except requests.RequestException as e:
        return False, f"RequestException: {e}"


def trigger_sync(base_url: str, token: str, owner: str, repo: str) -> tuple[bool, str | None]:
    """Trigger a pull-mirror sync in Gitea. Returns (ok, error_message)."""
    url = base_url.rstrip("/") + f"/api/v1/repos/{owner}/{repo}/mirror-sync"
    try:
        r = _post_json(url, token, {})
        if 200 <= r.status_code < 300:
            return True, None
        return False, f"HTTP {r.status_code}: {r.text.strip()}"
    except requests.RequestException as e:
        return False, f"RequestException: {e}"