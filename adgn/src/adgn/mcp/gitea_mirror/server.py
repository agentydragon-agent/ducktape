#!/usr/bin/env python3


"""Host-side MCP server for managing Gitea pull mirrors.

Configuration (env or kwargs):
  GITEA_BASE_URL: base URL to the Gitea instance (required)
  GITEA_TOKEN: access token with write:repository scope for target org/user (required)
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, TypeVar, cast
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError
import requests

from adgn.mcp.notifying_fastmcp import NotifyingFastMCP


@dataclass
class MirrorConfig:
    base_url: str
    token: str


class MirrorError(RuntimeError):
    pass


class TriggerMirrorSyncArgs(BaseModel):
    url: str
    model_config = ConfigDict(extra="forbid")


class TriggerMirrorSyncResponse(BaseModel):
    owner: str
    repo: str
    mirror_path: str
    mirror_updated: str  # Timestamp BEFORE sync (for comparison)
    sync_triggered: bool

    model_config = ConfigDict(extra="forbid")


class GetMirrorStatusArgs(BaseModel):
    owner: str
    repo: str
    model_config = ConfigDict(extra="forbid")


class GetMirrorStatusResponse(BaseModel):
    owner: str
    repo: str
    mirror_path: str
    mirror_updated: str
    is_mirror: bool

    model_config = ConfigDict(extra="forbid")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"token {token}", "Accept": "application/json", "Content-Type": "application/json"}


def _post_json(url: str, token: str, payload: dict[str, Any] | None = None, *, timeout: int = 15) -> requests.Response:
    return requests.post(url, headers=_headers(token), json=payload or {}, timeout=timeout)


def _get_json(url: str, token: str, *, timeout: int = 15) -> dict[str, Any]:
    resp = requests.get(url, headers=_headers(token), timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):  # narrow type for mypy and correctness
        raise MirrorError("Expected JSON object from Gitea API")
    return cast(dict[str, Any], data)


class _UserInfo(BaseModel):
    login: str

    # The user payload includes many fields we do not consume; ignore them so schema changes
    # surface via targeted validation rather than mass field definitions.
    model_config = ConfigDict(extra="ignore")


class _RepositoryInfo(BaseModel):
    mirror: bool
    mirror_updated: str

    # Gitea's repository payload carries numerous unrelated fields; ignore them and only
    # validate the subset we require for mirror orchestration.
    model_config = ConfigDict(extra="ignore")


T_Model = TypeVar("T_Model", bound=BaseModel)


def _get_typed_json(url: str, token: str, model_type: type[T_Model], *, timeout: int = 15) -> T_Model:
    payload = _get_json(url, token, timeout=timeout)
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:  # pragma: no cover - exercised via tests
        raise MirrorError(f"Unexpected payload for {model_type.__name__}") from exc


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
    payload = {"clone_addr": upstream, "repo_name": repo, "repo_owner": owner, "mirror": True, "private": False}
    resp = _post_json(migrate_url, cfg.token, payload)
    if resp.status_code not in (200, 201, 409):
        resp.raise_for_status()
        raise MirrorError(f"migrate failed ({resp.status_code}): {resp.text.strip()}")


def _trigger_sync(cfg: MirrorConfig, owner: str, repo: str) -> None:
    sync_url = f"{cfg.base_url.rstrip('/')}/api/v1/repos/{owner}/{repo}/mirror-sync"
    resp = _post_json(sync_url, cfg.token, {})
    if resp.status_code // 100 != 2:
        raise MirrorError(f"mirror-sync failed ({resp.status_code}): {resp.text.strip()}")


def _get_repo_info(cfg: MirrorConfig, owner: str, repo: str) -> _RepositoryInfo:
    """Get current repository info including mirror status and last update time."""
    repo_url = f"{cfg.base_url.rstrip('/')}/api/v1/repos/{owner}/{repo}"
    try:
        data = _get_typed_json(repo_url, cfg.token, _RepositoryInfo)
    except requests.RequestException as exc:
        raise MirrorError("failed to fetch repository metadata") from exc
    return data


def _resolve_owner(base_url: str, token: str) -> str:
    user_url = f"{base_url.rstrip('/')}/api/v1/user"
    data = _get_typed_json(user_url, token, _UserInfo)
    return data.login


def make_gitea_mirror_server(
    *,
    base_url: str | None = None,
    token: str | None = None,
) -> NotifyingFastMCP:
    cfg = MirrorConfig(
        base_url=str(base_url or os.environ.get("GITEA_BASE_URL", "")),
        token=str(token or os.environ.get("GITEA_TOKEN", "")),
    )
    if not cfg.base_url or not cfg.token:
        raise ValueError("Gitea mirror MCP requires GITEA_BASE_URL and GITEA_TOKEN")

    server = NotifyingFastMCP(
        "Gitea Mirror",
        instructions=(
            "Host-side Gitea mirror manager for async pull mirror syncing.\n\n"
            "Workflow:\n"
            "1. Call trigger_mirror_sync(url) to ensure mirror exists and start syncing (returns immediately)\n"
            "2. Poll get_mirror_status(owner, repo) until mirror_updated timestamp changes\n"
            "3. When timestamps differ, sync is complete and mirror is ready for cloning\n\n"
            "Typical sync time: 5-60 seconds depending on repository size. "
            "Recommended polling interval: 2-5 seconds."
        ),
    )

    @server.flat_model()
    def trigger_mirror_sync(input: TriggerMirrorSyncArgs) -> TriggerMirrorSyncResponse:
        """Ensure mirror exists and trigger async sync. Returns immediately.

        Creates a Gitea pull mirror if it doesn't exist, then triggers an async sync
        from the upstream repository. Returns the current mirror_updated timestamp.

        To detect sync completion: Poll get_mirror_status() and compare mirror_updated.
        When the timestamp changes, the sync is complete (typically 5-60 seconds).
        """
        owner = _resolve_owner(cfg.base_url, cfg.token)
        repo = _derive_repo_name(input.url)
        _ensure_mirror(cfg, input.url, owner, repo)

        # Get current state before triggering sync
        repo_data = _get_repo_info(cfg, owner, repo)

        # Trigger async sync
        _trigger_sync(cfg, owner, repo)

        return TriggerMirrorSyncResponse(
            owner=owner,
            repo=repo,
            mirror_path=f"{owner}/{repo}.git",
            mirror_updated=repo_data.mirror_updated,
            sync_triggered=True,
        )

    @server.flat_model()
    def get_mirror_status(input: GetMirrorStatusArgs) -> GetMirrorStatusResponse:
        """Get current mirror status including last update timestamp.

        Use this to poll for sync completion after calling trigger_mirror_sync().
        Compare the returned mirror_updated timestamp with the initial value.
        When timestamps differ, the sync is complete.

        Recommended polling: Every 2-5 seconds until mirror_updated changes.
        """
        repo_data = _get_repo_info(cfg, input.owner, input.repo)

        if not repo_data.mirror:
            raise MirrorError(f"repository {input.owner}/{input.repo} is not a mirror")

        return GetMirrorStatusResponse(
            owner=input.owner,
            repo=input.repo,
            mirror_path=f"{input.owner}/{input.repo}.git",
            mirror_updated=repo_data.mirror_updated,
            is_mirror=repo_data.mirror,
        )

    return server
