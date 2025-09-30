#!/usr/bin/env python3


"""Host-side MCP server for managing Gitea pull mirrors.

Tools:
  - ensure_mirror_and_sync(url: str): ensure a pull mirror exists for the upstream
    repository, trigger a sync, and wait for mirror_updated to change.

Configuration (env or kwargs):
  GITEA_BASE_URL: base URL to the Gitea instance (required)
  GITEA_TOKEN: access token with write:repository scope for target org/user (required)
  GITEA_POLL_INTERVAL_SECS: optional poll interval (default 2s)
  GITEA_POLL_TIMEOUT_SECS: optional timeout for mirror appearance (default 60s)
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, cast
from urllib.parse import urlparse

from adgn.mcp._shared.fastmcp_helpers import SafeFastMCP
from adgn.mcp._shared.fastmcp_helpers import mcp_flat_model
from pydantic import BaseModel, ConfigDict
import requests


@dataclass
class MirrorConfig:
    base_url: str
    token: str
    poll_interval_secs: float = 2.0
    poll_timeout_secs: float = 60.0


class MirrorError(RuntimeError):
    pass


class EnsureMirrorAndSyncArgs(BaseModel):
    url: str
    model_config = ConfigDict(extra="forbid")


class EnsureMirrorAndSyncResponse(BaseModel):
    owner: str
    repo: str
    mirror_path: str
    mirror_updated: str  # API spec: string (date-time); we return as-is

    model_config = ConfigDict(extra="forbid")


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _post_json(
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 15,
) -> requests.Response:
    return requests.post(
        url,
        headers=_headers(token),
        json=payload or {},
        timeout=timeout,
    )


def _get_json(url: str, token: str, *, timeout: int = 15) -> dict[str, Any]:
    resp = requests.get(url, headers=_headers(token), timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):  # narrow type for mypy and correctness
        raise MirrorError("Expected JSON object from Gitea API")
    return cast(dict[str, Any], data)


def _slug_component(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in value)
    slug = slug.strip("-")
    return slug or "repo"


def _derive_repo_name(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"URL missing host for Gitea mirror: {url}")
    path = parsed.path.removesuffix(".git").strip("/")
    components = [parsed.netloc, *([p for p in path.split("/") if p])]
    return "-".join(_slug_component(part) for part in components)


def _ensure_mirror(cfg: MirrorConfig, upstream: str, owner: str, repo: str) -> None:
    migrate_url = f"{cfg.base_url.rstrip('/')}/api/v1/repos/migrate"
    payload = {
        "clone_addr": upstream,
        "repo_name": repo,
        "repo_owner": owner,
        "mirror": True,
        "private": False,
    }
    resp = _post_json(migrate_url, cfg.token, payload)
    if resp.status_code not in (200, 201, 409):
        resp.raise_for_status()
        raise MirrorError(f"migrate failed ({resp.status_code}): {resp.text.strip()}")


def _trigger_sync(cfg: MirrorConfig, owner: str, repo: str) -> None:
    sync_url = f"{cfg.base_url.rstrip('/')}/api/v1/repos/{owner}/{repo}/mirror-sync"
    resp = _post_json(sync_url, cfg.token, {})
    if resp.status_code // 100 != 2:
        raise MirrorError(
            f"mirror-sync failed ({resp.status_code}): {resp.text.strip()}",
        )


def _wait_for_update(cfg: MirrorConfig, owner: str, repo: str) -> dict[str, Any]:
    repo_url = f"{cfg.base_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
    deadline = time.monotonic() + cfg.poll_timeout_secs
    last_updated: str | None = None
    while time.monotonic() < deadline:
        try:
            data = _get_json(repo_url, cfg.token)
        except requests.RequestException as exc:  # pragma: no cover - transient network
            raise MirrorError("failed to fetch repository metadata") from exc
        else:
            mirror_flag = data.get("mirror")
            if not isinstance(mirror_flag, bool) or not mirror_flag:
                raise MirrorError(
                    "repository is not marked as a mirror (mirror: boolean expected)"
                )
            updated_val = data.get("mirror_updated")
            if not isinstance(updated_val, str):
                raise MirrorError(
                    "unexpected shape: Repository.mirror_updated must be a string (date-time)"
                )
            if updated_val != last_updated:
                return data
            last_updated = updated_val
        time.sleep(cfg.poll_interval_secs)
    raise MirrorError(f"mirror did not update within {cfg.poll_timeout_secs}s")


def _resolve_owner(base_url: str, token: str) -> str:
    user_url = f"{base_url.rstrip('/')}/api/v1/user"
    data = _get_json(user_url, token)
    login = data.get("login")
    if not isinstance(login, str) or not login:
        raise MirrorError("unexpected shape: User.login (string) required")
    return login


def make_gitea_mirror_mcp(
    *,
    base_url: str | None = None,
    token: str | None = None,
    poll_interval_secs: float | None = None,
    poll_timeout_secs: float | None = None,
) -> SafeFastMCP:
    cfg = MirrorConfig(
        base_url=str(base_url or os.environ.get("GITEA_BASE_URL", "")),
        token=str(token or os.environ.get("GITEA_TOKEN", "")),
        poll_interval_secs=(
            float(os.environ.get("GITEA_POLL_INTERVAL_SECS", "2.0"))
            if poll_interval_secs is None
            else poll_interval_secs
        ),
        poll_timeout_secs=(
            float(os.environ.get("GITEA_POLL_TIMEOUT_SECS", "60.0"))
            if poll_timeout_secs is None
            else poll_timeout_secs
        ),
    )
    if not cfg.base_url or not cfg.token:
        raise ValueError("Gitea mirror MCP requires GITEA_BASE_URL and GITEA_TOKEN")

    server = SafeFastMCP(
        "gitea_mirror",
        instructions=(
            "Host-side Gitea mirror manager. ensure_mirror_and_sync(url) will ensure a pull mirror "
            "exists, trigger a sync, and wait for mirror_updated to change."
        ),
    )

    @mcp_flat_model(
        server,
        name="ensure_mirror_and_sync",
        title="Ensure mirror and sync",
        description="Ensure a Gitea pull mirror exists and syncs",
        structured_output=True,
    )
    def ensure_mirror_and_sync(
        input: EnsureMirrorAndSyncArgs,
    ) -> EnsureMirrorAndSyncResponse:
        owner = _resolve_owner(cfg.base_url, cfg.token)
        repo = _derive_repo_name(input.url)
        _ensure_mirror(cfg, input.url, owner, repo)
        _trigger_sync(cfg, owner, repo)
        repo_data = _wait_for_update(cfg, owner, repo)
        mu = repo_data.get("mirror_updated")
        if not isinstance(mu, str) or not mu:
            raise MirrorError(
                "unexpected shape: Repository.mirror_updated (string) required"
            )
        return EnsureMirrorAndSyncResponse(
            owner=owner,
            repo=repo,
            mirror_path=f"{owner}/{repo}.git",
            mirror_updated=mu,
        )

    return server
