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
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from opentelemetry import trace
from pydantic import BaseModel

from devinfra.claude.claude_api.hooks.common import HookOutputBase
from devinfra.claude.claude_api.hooks.config_change import ConfigChangeInput
from devinfra.claude.claude_api.hooks.cwd_changed import CwdChangedInput
from devinfra.claude.claude_api.hooks.dispatch_input import AnyHookInput
from devinfra.claude.claude_api.hooks.file_changed import FileChangedInput
from devinfra.claude.claude_api.hooks.instructions_loaded import InstructionsLoadedInput
from devinfra.claude.claude_api.hooks.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.hooks.pre_tool_use import PreToolUseInput
from devinfra.claude.claude_api.hooks.session_end import SessionEndInput
from devinfra.claude.claude_api.hooks.session_start import SessionStartHookInput
from devinfra.claude.claude_api.hooks.setup import SetupInput
from devinfra.claude.claude_api.hooks.worktree_create import WorktreeCreateInput
from devinfra.claude.claude_api.hooks.worktree_remove import WorktreeRemoveInput
from devinfra.claude.hook_config import HookConfig
from devinfra.claude.hook_daemon.models import HookRequest, HookResponse
from devinfra.claude.hook_daemon.post_tool_use import evaluate as evaluate_post
from devinfra.claude.hook_daemon.pre_tool_use import evaluate as evaluate_pre
from devinfra.claude.hook_daemon.session import Session
from devinfra.claude.hook_daemon.session_start.handler import CallerContext, handle as handle_session_start
from devinfra.claude.hook_daemon.session_start.http_client import build_http_client
from devinfra.claude.hook_daemon.tracing import DeferredOtlpExporter
from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import HookSettings, is_web_mode

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 1800  # 30 minutes
IDLE_CHECK_INTERVAL_SECONDS = 30

app = FastAPI()


@app.middleware("http")
async def _log_exceptions(request: Request, call_next):
    """Log full traceback for unhandled exceptions instead of silent 500."""
    try:
        return await call_next(request)
    except Exception:
        tb_str = traceback.format_exc()
        logger.exception("Unhandled exception in %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": tb_str})


def configure(daemon_dir: Path, otlp_exporter: DeferredOtlpExporter) -> None:
    """Set daemon runtime directory and shared config. Call before starting uvicorn."""
    app.state.daemon_dir = daemon_dir
    app.state.settings = HookSettings()
    app.state.otlp_exporter = otlp_exporter
    app.state.last_request_time = time.monotonic()
    app.state.sessions = {}  # dict[str, Session]
    # Proxies are started lazily on the first SessionStart hook, not here.


def _get_or_create_session(session_id: str, env: dict[str, str]) -> Session:
    """Return existing Session for session_id, or create and register one."""
    sessions: dict[str, Session] = app.state.sessions
    if existing := sessions.get(session_id):
        return existing
    session = Session(session_id=session_id, paths=SessionPaths.from_env(session_id, env))
    sessions[session_id] = session
    return session


def _save_session_env(env: dict[str, str]) -> None:
    """Persist caller's env to disk for debuggability and daemon restart survival."""
    daemon_dir: Path | None = getattr(app.state, "daemon_dir", None)
    if daemon_dir is None:
        return
    env_file = daemon_dir / "session_env.json"
    env_file.write_text(json.dumps(env, indent=2))


# Non-REPL hooks: Claude Code delivers systemMessage to the UI notification
# callback only, not to the model conversation. Flushing mailbox messages into
# these would waste them — the model never sees them, so they'd be silently lost.
# All other hook types are REPL hooks where systemMessage is injected into the
# conversation as a hook_system_message attachment that the model reads.
_NON_REPL_HOOK_TYPES = (
    SessionStartHookInput,
    SessionEndInput,
    SetupInput,
    CwdChangedInput,
    FileChangedInput,
    InstructionsLoadedInput,
    WorktreeCreateInput,
    WorktreeRemoveInput,
    ConfigChangeInput,
)


def _apply_mailbox(output: HookOutputBase | None, session: Session, hook: AnyHookInput) -> HookOutputBase | None:
    """Drain session mailbox and append messages to output.system_message.

    Only flushes on REPL hooks — those where Claude Code delivers systemMessage
    to the model conversation (as a hook_system_message attachment). Non-REPL
    hooks (SessionStart, Setup, file watchers, etc.) deliver systemMessage to
    the UI notification callback only; flushing there would waste the messages.
    """
    if isinstance(hook, _NON_REPL_HOOK_TYPES):
        return output
    if bg_messages := session.drain_messages():
        if output is None:
            output = HookOutputBase()
        formatted = "Messages from hook daemon mailbox:\n" + "\n".join(f"- {m}" for m in bg_messages)
        parts = [output.system_message, formatted] if output.system_message else [formatted]
        output.system_message = "\n\n".join(parts)
    return output


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

        session = _get_or_create_session(req.hook.session_id, req.env)

        output: HookOutputBase | None = None
        match req.hook:
            case SessionStartHookInput():
                hook_config = HookConfig.load_from_repo(Path(req.hook.cwd))
                web_mode = req.env.get("CLAUDE_CODE_REMOTE") == "true"
                profile = hook_config.resolve_profile(web_mode, override=app.state.settings.profile)
                await session.start_proxy(profile)
                ctx = CallerContext.from_env(req.env)
                with build_http_client(req.env) as http:
                    output = await handle_session_start(
                        session, req.hook, app.state.settings, ctx=ctx, http=http, otlp_exporter=app.state.otlp_exporter
                    )
            case PreToolUseInput():
                output = evaluate_pre(req.hook)
            case PostToolUseInput():
                output = evaluate_post(req.hook)
            case _:
                pass  # All other hooks: noop

        output = _apply_mailbox(output, session, req.hook)

        # Guard: non-REPL hooks deliver systemMessage to the UI notification
        # callback only — the model never sees it. If we accidentally set it,
        # catch the bug here rather than silently losing the message.
        if output is not None and output.system_message is not None and isinstance(req.hook, _NON_REPL_HOOK_TYPES):
            raise AssertionError(
                f"Bug: system_message set on non-REPL hook {hook_name!r}. "
                f"The model will never see this message. Use additionalContext "
                f"or initialUserMessage in hookSpecificOutput instead."
            )

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
async def update_proxy_creds(req: _UpdateProxyCredsRequest) -> None:
    """Update in-process proxy credentials. Called by bazel_wrapper on each invocation."""
    for s in app.state.sessions.values():
        s.set_proxy_creds(req.https_proxy)
    logger.debug("Updated proxy credentials via RPC")


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
    for session in app.state.sessions.values():
        session.stop()
