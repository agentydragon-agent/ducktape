"""FastAPI app for the hook daemon.

Handles all Claude Code hook types over UDS. Imports expensive modules once at
startup (pydantic, opentelemetry, session_start) so individual hook calls are fast.

The auth proxy runs in-process as daemon threads, started on the first SessionStart
hook (not at daemon startup). This ensures each session owns its proxy lifecycle and
avoids port conflicts during daemon startup when a previous session's proxy is still
running on the same port.
"""

import asyncio
import json
import logging
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from opentelemetry import trace
from pydantic import BaseModel

from devinfra.claude.auth_proxy.proxy import AuthForwardingProxy, UdsRemoteProxy
from devinfra.claude.auth_proxy.vars import get_upstream_proxy_url
from devinfra.claude.claude_api.hooks.dispatch_output import AnyHookOutput
from devinfra.claude.claude_api.hooks.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.hooks.pre_tool_use import PreToolUseInput
from devinfra.claude.claude_api.hooks.session_start import SessionStartHookInput
from devinfra.claude.hook_config import HookConfig
from devinfra.claude.hook_daemon.models import HookRequest, HookResponse, UpdateProxyCredsResponse
from devinfra.claude.hook_daemon.post_tool_use import evaluate as evaluate_post
from devinfra.claude.hook_daemon.pre_tool_use import evaluate as evaluate_pre
from devinfra.claude.hook_daemon.session_start.handler import handle as handle_session_start
from devinfra.claude.hook_daemon.session_start.http_client import build_http_client
from devinfra.claude.hook_daemon.tracing import DeferredOtlpExporter
from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import HookSettings, ProxyMode, is_web_mode

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 1800  # 30 minutes
IDLE_CHECK_INTERVAL_SECONDS = 30

app = FastAPI()


@dataclass
class ProxyState:
    """In-process proxy instances, started lazily on the first SessionStart."""

    tcp: AuthForwardingProxy | None = None
    uds_remote: UdsRemoteProxy | None = None  # Bazel --remote_proxy
    uds_bes: UdsRemoteProxy | None = None  # Bazel --bes_proxy

    def set_creds(self, https_proxy: str) -> None:
        """Update upstream credentials on all running proxies."""
        if self.tcp is not None:
            self.tcp.set_creds(https_proxy)
        if self.uds_remote is not None:
            self.uds_remote.set_creds(https_proxy)
        if self.uds_bes is not None:
            self.uds_bes.set_creds(https_proxy)

    def any_running(self) -> bool:
        return self.tcp is not None or self.uds_remote is not None or self.uds_bes is not None

    def stop_all(self) -> None:
        if self.tcp is not None:
            logger.info("Stopping in-process auth proxy...")
            self.tcp.stop()
        if self.uds_remote is not None:
            logger.info("Stopping UDS remote proxy...")
            self.uds_remote.stop()
        if self.uds_bes is not None:
            logger.info("Stopping UDS BES proxy...")
            self.uds_bes.stop()


def configure(daemon_dir: Path, otlp_exporter: DeferredOtlpExporter) -> None:
    """Set daemon runtime directory and shared config. Call before starting uvicorn."""
    app.state.daemon_dir = daemon_dir
    app.state.settings = HookSettings()
    app.state.otlp_exporter = otlp_exporter
    app.state.last_request_time = time.monotonic()
    app.state.proxies = ProxyState()
    app.state.background_tasks = set[asyncio.Task[object]]()
    # Proxies are started lazily on the first SessionStart hook, not here.


async def _start_session_proxy(session_id: str, web_mode: bool, hook_config: HookConfig) -> None:
    """Start proxy infrastructure for the current session.

    In UDS mode (default): UDS proxies are started for --remote_proxy and/or
    --bes_proxy as configured. Bazel uses these for gRPC; BCR fetches use
    JAVA_TOOL_OPTIONS (set by Anthropic).

    In TCP mode (legacy): the TCP HTTP CONNECT proxy is also started.

    Called at the start of SessionStart handling — not at daemon startup.
    Idempotent: no-op if proxies are already running.
    """
    profile = hook_config.profile(web_mode)
    upstream_url = get_upstream_proxy_url()
    paths = SessionPaths(session_id=session_id, home=Path.home(), xdg_cache_home=Path.home())
    proxies: ProxyState = app.state.proxies
    settings: HookSettings = app.state.settings

    # CLEANUP(2026-03-26): Remove TCP proxy once UDS mode is confirmed stable.
    if settings.proxy_mode == ProxyMode.TCP and proxies.tcp is None:
        tcp = AuthForwardingProxy(listen_port=0)
        tcp.start()
        proxies.tcp = tcp
        logger.info("Auth proxy started in-process on port %d (tcp mode)", tcp.listen_port)

    if proxies.uds_remote is None and profile.bazel_remote_proxy is not None:
        uds = UdsRemoteProxy(sock_path=paths.bazel_remote_proxy_sock, remote_target=profile.bazel_remote_proxy.target)
        if upstream_url:
            uds.set_creds(upstream_url)
        uds.start()
        proxies.uds_remote = uds

    if proxies.uds_bes is None and profile.bazel_bes_proxy is not None:
        uds = UdsRemoteProxy(sock_path=paths.bazel_bes_proxy_sock, remote_target=profile.bazel_bes_proxy.target)
        if upstream_url:
            uds.set_creds(upstream_url)
        uds.start()
        proxies.uds_bes = uds


def _save_session_env(env: dict[str, str]) -> None:
    """Persist caller's env to disk for debuggability and daemon restart survival."""
    daemon_dir: Path | None = getattr(app.state, "daemon_dir", None)
    if daemon_dir is None:
        return
    env_file = daemon_dir / "session_env.json"
    env_file.write_text(json.dumps(env, indent=2))


@app.post("/hook")
async def handle_hook(req: HookRequest) -> Response:
    app.state.last_request_time = time.monotonic()

    tracer = trace.get_tracer(__name__)
    hook_name = req.hook.hook_event_name

    with tracer.start_as_current_span(
        f"hook.{hook_name}",
        attributes={
            "hook.event_name": hook_name,
            "hook.session_id": req.hook.session_id,
            "hook.input": req.model_dump_json(),
        },
    ) as span:
        # Persist env to disk on every call
        _save_session_env(req.env)

        output: AnyHookOutput | None = None
        match req.hook:
            case SessionStartHookInput():
                hook_config = HookConfig.load_from_repo(Path(req.hook.cwd))
                web_mode = req.env.get("CLAUDE_CODE_REMOTE") == "true"
                await _start_session_proxy(req.hook.session_id, web_mode, hook_config)
                paths = SessionPaths.from_env(req.hook.session_id, req.env)
                proxies: ProxyState = app.state.proxies
                with build_http_client(req.env) as http:
                    output = await handle_session_start(
                        req.hook,
                        paths,
                        app.state.settings,
                        caller_env=req.env,
                        http=http,
                        otlp_exporter=app.state.otlp_exporter,
                        proxy=proxies.tcp,
                        background_tasks=app.state.background_tasks,
                    )
            case PreToolUseInput():
                output = evaluate_pre(req.hook)
            case PostToolUseInput():
                output = evaluate_post(req.hook)
            case _:
                pass  # All other hooks: noop

        resp = HookResponse(output=output)
        # exclude_none: the client may run an older version of the models
        # (e.g. Nix-installed claude-hook) that uses extra="forbid" on
        # CamelModel. New Optional fields default to None; if serialized
        # as null they become unknown extras on the old client → ValidationError.
        # Omitting None fields keeps the wire format forward-compatible.
        resp_json = resp.model_dump_json(by_alias=True, exclude_none=True)

        span.set_attribute("hook.output", resp_json)
        logger.info("hook %s → %s", hook_name, resp_json)

        return Response(content=resp_json, media_type="application/json")


class _UpdateProxyCredsRequest(BaseModel):
    https_proxy: str


@app.post("/update-proxy-creds")
async def update_proxy_creds(req: _UpdateProxyCredsRequest) -> UpdateProxyCredsResponse:
    """Update in-process proxy credentials. Called by bazel_wrapper on each invocation."""
    proxies: ProxyState = app.state.proxies
    if not proxies.any_running():
        raise HTTPException(status_code=503, detail="No proxy running")
    proxies.set_creds(req.https_proxy)
    logger.debug("Updated proxy credentials via RPC")
    # Return TCP proxy URL if available (legacy mode), otherwise a placeholder.
    proxy_url = f"http://localhost:{proxies.tcp.listen_port}" if proxies.tcp else "uds-only"
    return UpdateProxyCredsResponse(proxy_url=proxy_url)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check — does NOT reset idle timer."""
    return {"status": "ok"}


async def _idle_watchdog() -> None:
    """Background task: exit after IDLE_TIMEOUT_SECONDS of no requests."""
    while True:
        await asyncio.sleep(IDLE_CHECK_INTERVAL_SECONDS)
        idle_seconds = time.monotonic() - app.state.last_request_time
        if idle_seconds >= IDLE_TIMEOUT_SECONDS:
            logger.info("Idle timeout reached (%.0fs), shutting down", idle_seconds)
            signal.raise_signal(signal.SIGTERM)
            return


@app.on_event("startup")
async def _start_idle_watchdog() -> None:
    if is_web_mode():
        # Web sessions are managed by Anthropic's environment manager — don't
        # self-terminate. The container is torn down externally when the session ends.
        logger.info("Web mode: idle watchdog disabled")
        return
    app.state.watchdog_task = asyncio.create_task(_idle_watchdog())


@app.on_event("shutdown")
async def _stop_proxy() -> None:
    """Stop the in-process proxies on daemon shutdown."""
    proxies: ProxyState | None = getattr(app.state, "proxies", None)
    if proxies is not None:
        proxies.stop_all()
