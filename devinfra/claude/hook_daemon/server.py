"""FastAPI app for the hook daemon.

Handles all Claude Code hook types over UDS. Imports expensive modules once at
startup (pydantic, opentelemetry, session_start) so individual hook calls are fast.
"""

import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

from fastapi import FastAPI

from devinfra.claude.claude_api.hooks.dispatch_output import AnyHookOutput
from devinfra.claude.claude_api.hooks.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.hooks.pre_tool_use import PreToolUseInput
from devinfra.claude.claude_api.hooks.session_start import SessionStartHookInput
from devinfra.claude.hook_daemon.models import HookRequest, HookResponse
from devinfra.claude.post_tool_use import evaluate as evaluate_post
from devinfra.claude.pre_tool_use import evaluate as evaluate_pre
from devinfra.claude.settings import HookSettings

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 300  # 5 minutes
IDLE_CHECK_INTERVAL_SECONDS = 30

# Mutable state — set by configure() before app starts
_daemon_dir: Path | None = None
_last_request_time: float = time.monotonic()

# Store reference to prevent GC (RUF006)
_watchdog_task: asyncio.Task[None] | None = None

app = FastAPI()


def configure(daemon_dir: Path) -> None:
    """Set daemon runtime directory (for env persistence, logs). Call before starting uvicorn."""
    global _daemon_dir  # noqa: PLW0603 — module-level state set once before server starts
    _daemon_dir = daemon_dir


def _save_session_env(env: dict[str, str]) -> None:
    """Persist caller's env to disk for debuggability and daemon restart survival."""
    if _daemon_dir is None:
        return
    env_file = _daemon_dir / "session_env.json"
    env_file.write_text(json.dumps(env, indent=2))


@app.post("/hook")
async def handle_hook(req: HookRequest) -> HookResponse:
    global _last_request_time  # noqa: PLW0603 — lightweight timestamp update per request
    _last_request_time = time.monotonic()

    # Log request
    logger.info("REQ %s: %s", req.hook.hook_event_name, req.model_dump_json())

    # Persist env to disk on every call
    _save_session_env(req.env)

    output: AnyHookOutput | None = None
    match req.hook:
        case SessionStartHookInput():
            output = await _handle_session_start(req.hook, req.env)
        case PreToolUseInput():
            output = evaluate_pre(req.hook)
        case PostToolUseInput():
            output = evaluate_post(req.hook)
        case _:
            pass  # All other hooks: noop (logged below)

    # Log response
    resp = HookResponse(output=output)
    logger.info("RSP %s: %s", req.hook.hook_event_name, resp.model_dump_json(by_alias=True, exclude_none=True))

    return resp


async def _handle_session_start(hook_input: SessionStartHookInput, env: dict[str, str]) -> AnyHookOutput | None:
    """Handle SessionStart by running the existing session_start logic.

    Patches os.environ with the caller's env so session_start code (which reads
    os.environ) gets the correct values. The full refactor to pass env dicts
    through session_start internals can come later.
    """
    # Deferred import to avoid circular dependency at module level
    from devinfra.claude.session_start import _async_handle  # noqa: PLC0415

    # Patch os.environ with caller's env for session_start code
    old_environ = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    try:
        session_dir = Path.home() / ".claude" / "session-env" / hook_input.session_id
        settings = HookSettings(session_dir=session_dir)
        return await _async_handle(hook_input, settings)
    finally:
        os.environ.clear()
        os.environ.update(old_environ)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check — does NOT reset idle timer."""
    return {"status": "ok"}


async def _idle_watchdog() -> None:
    """Background task: exit after IDLE_TIMEOUT_SECONDS of no requests."""
    while True:
        await asyncio.sleep(IDLE_CHECK_INTERVAL_SECONDS)
        idle_seconds = time.monotonic() - _last_request_time
        if idle_seconds >= IDLE_TIMEOUT_SECONDS:
            logger.info("Idle timeout reached (%.0fs), shutting down", idle_seconds)
            signal.raise_signal(signal.SIGTERM)
            return


@app.on_event("startup")
async def _start_idle_watchdog() -> None:
    global _watchdog_task  # noqa: PLW0603
    _watchdog_task = asyncio.create_task(_idle_watchdog())
