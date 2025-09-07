#!/usr/bin/env python3
"""
Combo Git + Container MCP Server

- One container per MCP session (created on initialize, removed on shutdown)
- Container has no network and mounts a host-side RO bare-repo store
- Tools:
  - obtain_repo(url, ref?, branch?, submodules?=false) → fetch host bare repo, clone inside container using
    --reference to RO store, return working-copy path and HEAD SHA
  - docker_exec(cmd, cwd?, env?, user?, tty?, shell?, timeout_secs?) → run a command inside the per-session
    container (no network)
- Server description (non-tool): includes mount points, workspace root, image metadata,
  and the embedded Dockerfile (or docker history CreatedBy) as single source of truth;
  exposed via serverInfo.description

Colima note: host bind path must be under $HOME.
"""

from __future__ import annotations

import os
import shlex
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import docker
from docker.models.containers import Container
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from .._shared.container_session import (
    ContainerSessionState,
    make_container_lifespan,
    register_exec_tool,
    register_container_resources,
    NetworkMode,
)
from .tools.gitea_api import trigger_sync
from .._shared.container_session import (
    _container_exec as shared_container_exec,
)


@dataclass
class PublicGitState:
    docker_client: docker.DockerClient | None
    container: Container | None
    store_host: Path
    mount_point: str
    workspace_root: str
    image: str
    default_timeout: float | None
    use_timeout_wrapper: bool
    gitea_base_url: str | None = None
    gitea_token: str | None = None
    gitea_sync_before_clone: bool = False


# ---- Defaults / config
DEFAULT_MOUNT_POINT = "/mnt/git-bare"
DEFAULT_WORKSPACE = "/workspace"


# FastMCP server factory with per-session lifespan (container per session)
def _public_git_lifespan_factory(
    *,
    store_host: Path,
    image: str,
    mount_point: str = DEFAULT_MOUNT_POINT,
    workspace_root: str = DEFAULT_WORKSPACE,
    gitea_base_url: str | None = None,
    gitea_token: str | None = None,
    gitea_sync_before_clone: bool = True,
):
    async def lifespan(_server: FastMCP):  # yields PublicGitState
        # Build per-session state
        st = PublicGitState(
            docker_client=None,
            container=None,
            store_host=store_host.resolve(),
            mount_point=mount_point,
            workspace_root=workspace_root,
            image=image,
            default_timeout=None,
            use_timeout_wrapper=True,
            gitea_base_url=gitea_base_url,
            gitea_token=gitea_token,
            gitea_sync_before_clone=gitea_sync_before_clone,
        )
        _ensure_dir(st.store_host)
        # Compute and publish server description using host-side Docker image history (no container access)
        img = _init_docker().images.get(st.image)
        img_id, tags = img.id, img.tags
        history_lines: list[str] = []
        hist = _init_docker().api.history(img_id)  # type: ignore[attr-defined]
        for entry in hist or []:
            created_by = (entry.get("CreatedBy") or "").lstrip("/bin/sh -c ").removeprefix("#(nop) ").strip()
            if created_by:
                history_lines.append(f"  - {created_by}")
        body = [
            "Public Git (Gitea-backed) MCP server.",
            f"- Mount (read-only bare Git mirrors): {st.mount_point}",
            f"- Workspace (writable): {st.workspace_root}",
            f"- Container image: {img_id} {' '.join(tags) if tags else ''}",
            "Image history (CreatedBy):",
            "\n".join(history_lines[:100]) if history_lines else "  - (none)",
            "Tooling in container:",
            "  - gitea_mirror.py is on PATH (from /opt/public_git_tools)",
            "  - Env provided: GITEA_BASE_URL, GITEA_TOKEN; MOUNT_POINT and WORKING_DIR",
            "Usage (agent runs these inside the container):",
            "  - gitea_mirror.py https://host/owner/repo.git",
            "    → Ensures mirror exists, triggers sync, and clones under $WORKING_DIR/<host>/<path> using --reference from $MOUNT_POINT",
        ]
        _server.server_info.description = "\n".join(body)  # type: ignore[attr-defined]
        # Start container for this session
        vols = {str(st.store_host): {"bind": st.mount_point, "mode": "ro"}}
        st.container = _start_container(
            image=st.image,
            volumes=vols,
            workspace=st.workspace_root,
        )
        try:
            yield st
        finally:
            if st.container is not None:
                st.container.stop(timeout=1)

    return lifespan


# ---- FastMCP tool registration ----


def _register_obtain_code_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        parameters={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string"},
                "ref": {"type": "string"},
                "branch": {"type": "string"},
            },
        }
    )
    def obtain_code(
        ctx: Context[ServerSession, ContainerSessionState],
        url: str,
        ref: str | None = None,
        branch: str | None = None,
    ) -> dict[str, Any]:
        s = ctx.request_context.lifespan_context
        if s.container is None:
            raise RuntimeError("container not started")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("public_git supports only http/https URLs")
        key = UrlKey(origin_url=url)
        rel = key.storage_key_gitea
        # Gitea: always attempt to sync mirror before clone
        # Optionally trigger a Gitea mirror sync; best-effort only
        sync_attempted = False
        sync_ok = False
        sync_error = None
        try:
            owner, repo_git = rel.split("/", 1)
            repo = repo_git[:-4] if repo_git.endswith(".git") else repo_git
        except Exception:
            owner, repo = "", ""
        if s.gitea_base_url and s.gitea_token and owner and repo:
            sync_attempted = True
            sync_ok, sync_error = trigger_sync(s.gitea_base_url, s.gitea_token, owner, repo)
        _ensure_bare_and_fetch(s.store_host, key)
        dest = f"{s.working_dir}/{key.pretty}"
        clone_cmd = [
            "sh",
            "-lc",
            (
                f"mkdir -p {shlex.quote(os.path.dirname(dest))} && "
                f"git clone --reference {shlex.quote(s.mount_point + '/' + rel)} "
                f"file://{shlex.quote(s.mount_point + '/' + rel)} {shlex.quote(dest)} && "
                + (
                    f"git -C {shlex.quote(dest)} checkout --detach {shlex.quote(str(ref))} && "
                    if ref
                    else (f"git -C {shlex.quote(dest)} checkout {shlex.quote(str(branch))} && " if branch else "")
                )
                + f"git -C {shlex.quote(dest)} rev-parse HEAD"
            ),
        ]
        res = shared_container_exec(container=s.container, cmd=clone_cmd)
        if (res.get("exit_code")) != 0:
            raise RuntimeError(f"clone failed: {res.get('stderr') or res.get('stdout')}")
        head_sha = (res.get("stdout") or "").strip().splitlines()[-1] if res.get("stdout") else ""
        return {
            "path": dest,
            "head_sha": head_sha,
            "storage_key": rel,
            "pretty_path": dest,
            "sync_attempted": sync_attempted,
            "sync_ok": sync_ok,
            "sync_error": sync_error,
        }


def make_public_git_mcp(
    *,
    store_host: str | Path,
    image: str,
    mount_point: str = DEFAULT_MOUNT_POINT,
    working_dir: str = DEFAULT_WORKSPACE,
    gitea_base_url: str | None = None,
    gitea_token: str | None = None,
    gitea_sync_before_clone: bool = True,
    network_mode: NetworkMode = NetworkMode.NONE,
    volumes: dict[str, dict[str, str]] | list[str] | None = None,
) -> FastMCP:
    """Create a FastMCP server for public_git with per-session container lifecycle.

    Required:
      - store_host: path to Gitea repositories root (…/git/repositories)
      - image: Docker image to use for the per-session container
    Optional:
      - mount_point (default "/mnt/git-bare"), working_dir (default "/workspace"),
        gitea_base_url, gitea_token, gitea_sync_before_clone, network_mode (default NONE), volumes (Docker volumes spec)
    """
    # Use shared container lifespan (host-side docker history description, per-session container)
    store_host_path = Path(store_host).resolve()
    # Default to RO bind of the store under mount_point if caller didn't supply volumes
    vols = volumes
    if vols is None:
        vols = {str(store_host_path): {"bind": mount_point, "mode": "ro"}}
    # Mount public_git tools into the container for convenient CLI usage
    tools_host_dir = (Path(__file__).parent / "tools").resolve()
    if isinstance(vols, dict):
        vols[str(tools_host_dir)] = {"bind": "/opt/public_git_tools", "mode": "ro"}

    # Pass Gitea and path env into the container
    env = {
        "PATH": f"/opt/public_git_tools:{os.environ.get('PATH', '')}",
        "GITEA_BASE_URL": gitea_base_url or "",
        "GITEA_TOKEN": gitea_token or "",
        "MOUNT_POINT": mount_point,
        "WORKING_DIR": working_dir,
    }

    lifespan = make_container_lifespan(
        image=image,
        working_dir=working_dir,
        volumes=vols,
        describe=True,
        network_mode=network_mode,
        environment=env,
    )
    mcp = FastMCP(
        "public_git",
        instructions="Public Git (Gitea) MCP. See resource container.info for per-session details.",
        lifespan=lifespan,
    )
    # Register a standard container.info resource
    register_container_resources(mcp)
    # Compose a host-side description with image history and in-container tooling notes
    img = _init_docker().images.get(image)
    img_id, tags = img.id, img.tags
    hist = _init_docker().api.history(img_id)  # type: ignore[attr-defined]
    history_lines = []
    for entry in hist or []:
        created_by = (entry.get("CreatedBy") or "").lstrip("/bin/sh -c ").removeprefix("#(nop) ").strip()
        if created_by:
            history_lines.append(f"  - {created_by}")

    # Summarize volumes (dict style only)
    vol_lines: list[str] = []
    if isinstance(vols, dict):
        for host, spec in vols.items():
            bind = (spec or {}).get("bind") if isinstance(spec, dict) else None
            mode = (spec or {}).get("mode") if isinstance(spec, dict) else None
            if bind:
                vol_lines.append(f"  - {host} → {bind}{' (' + mode + ')' if mode else ''}")

    body = [
        "Public Git (Gitea-backed) MCP server.",
        f"- Working dir: {working_dir}",
        f"- Network mode: {network_mode.value}",
        f"- Container image: {img_id} {' '.join(tags) if tags else ''}",
        "- Volumes:",
        *(vol_lines or ["  - (none)"]),
        "Image history (CreatedBy):",
        "\n".join(history_lines[:100]) if history_lines else "  - (none)",
        "In-container helper:",
        "  - /opt/public_git_tools/gitea_mirror.py (invoke via: python3 /opt/public_git_tools/gitea_mirror.py)",
        "  - Env: GITEA_BASE_URL, GITEA_TOKEN, MOUNT_POINT, WORKING_DIR",
        "  - Requires network_mode != NONE for Gitea API access",
        "Usage inside container:",
        "  - python3 /opt/public_git_tools/gitea_mirror.py https://host/owner/repo.git",
        "    → Ensures/updates pull mirror in Gitea and clones under $WORKING_DIR/<host>/<path> using --reference from $MOUNT_POINT",
    ]
    mcp.server_info.description = "\n".join(body)  # type: ignore[attr-defined]
    # Use shared exec; register session_info and obtain_code locally
    register_exec_tool(mcp, tool_name="exec")
    # session_info not registered: description above includes static container details and usage
    _register_obtain_code_tool(mcp)
    return mcp


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class UrlKey:
    """Strong URL holder; derives storage_key/pretty lazily from origin_url (http/https only)."""

    origin_url: str

    @property
    def parsed(self) -> urllib.parse.ParseResult:
        return urlparse(self.origin_url)

    @property
    def host(self) -> str:
        return (self.parsed.hostname or self.parsed.netloc or "unknown").lower()

    @property
    def path(self) -> str:
        p = self.parsed.path.strip("/")
        return p[:-4] if p.endswith(".git") else p

    @property
    def storage_key(self) -> str:
        return f"{self.host}/{self.path}.git"

    @property
    def storage_key_gitea(self) -> str:
        segs = [s for s in self.path.split("/") if s]
        if len(segs) < 2:
            raise ValueError(f"URL path too short for gitea layout: {self.path}")
        owner, repo = segs[-2], segs[-1]
        return f"{owner}/{repo}.git"

    @property
    def pretty(self) -> str:
        return f"{self.host}/{self.path}"


def _ensure_bare_and_fetch(store: Path, key: UrlKey) -> Path:
    # Gitea layout only: repo must exist under <store>/<owner>/<repo>.git
    bare_dir = store / key.storage_key_gitea
    if not bare_dir.exists():
        raise FileNotFoundError(f"Mirror not found at {bare_dir}. Create a pull-mirror in Gitea and retry.")
    return bare_dir


# ---- Docker helpers


def _init_docker() -> docker.DockerClient:
    # New client per call is fine; docker-py caches connections internally
    return docker.from_env()


def _start_container(image: str, volumes: dict[str, dict[str, str]], workspace: str, user: str | None) -> Container:
    client = _init_docker()
    container = client.containers.run(
        image=image,
        command=["/bin/sh", "-lc", "sleep infinity"],
        detach=True,
        tty=False,
        working_dir=workspace,
        network_mode="none",
        volumes=volumes,
        user=user if user else None,
        auto_remove=True,
    )
    return container




def _container_exec(
    container: Container,
    *,
    cmd: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    user: str | None = None,
    tty: bool = False,
    shell: bool = False,
    timeout_secs: float | None = None,
) -> dict[str, Any]:
    # Optionally wrap with timeout inside container for reliable timeouts
    prepared_cmd: list[str] | str
    if timeout_secs and timeout_secs > 0:
        timeout_arg = f"timeout -s TERM {int(timeout_secs)}"
        if shell:
            prepared_cmd = f"{timeout_arg} {shlex.join(cmd)}"
        else:
            prepared_cmd = ["sh", "-lc", f"{timeout_arg} {shlex.join(cmd)}"]
    else:
        prepared_cmd = shlex.join(cmd) if shell else cmd

    if (
        shell
        and not (isinstance(prepared_cmd, list) and prepared_cmd[:2] == ["sh", "-lc"])
        and not isinstance(prepared_cmd, list)
    ):
        exec_cmd: list[str] | str = ["sh", "-lc", prepared_cmd]  # type: ignore[list-item]
    else:
        exec_cmd = prepared_cmd

    exec_id = container.client.api.exec_create(
        container=container.id,
        cmd=exec_cmd,
        stdout=True,
        stderr=True,
        stdin=False,
        tty=tty,
        user=user,
        workdir=cwd,
        environment=env,
    )["Id"]

    stdout_buf = bytearray()
    stderr_buf = bytearray()

    # Stream demux
    for out_err in container.client.api.exec_start(exec_id, stream=True, demux=True):
        if not isinstance(out_err, tuple):
            if out_err:
                stdout_buf.extend(out_err)
            continue
        out_b, err_b = out_err
        if out_b:
            stdout_buf.extend(out_b)
        if err_b:
            stderr_buf.extend(err_b)

    inspect = container.client.api.exec_inspect(exec_id)
    return {
        "exit_code": inspect.get("ExitCode"),
        "timed_out": False,  # best-effort; wrapper enforces real timeout
        "stdout": stdout_buf.decode(errors="replace"),
        "stderr": stderr_buf.decode(errors="replace"),
    }
