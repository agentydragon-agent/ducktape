"""Unified Claude Code hook entry point.

Reads JSON from stdin, parses into a discriminated union (AnyHookInput),
then dispatches to the appropriate handler via match/isinstance.
Initializes OTEL tracing from .claude_hooks/config.yaml if available.
Uses lazy imports to avoid loading heavy dependencies (mako, asyncio)
for lightweight hooks like PreToolUse and PostToolUse.
"""

import asyncio
import os
import sys
import traceback
from pathlib import Path

from pydantic import TypeAdapter

from devinfra.claude.claude_api.hook_dispatch_input import AnyHookInput
from devinfra.claude.claude_api.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.pre_tool_use import PreToolUseInput
from devinfra.claude.claude_api.session_start_input import SessionStartHookInput
from devinfra.claude.hook_config import HookConfig, OtelConfig

_adapter: TypeAdapter[AnyHookInput] = TypeAdapter(AnyHookInput)


def _load_otel_config(cwd: Path) -> OtelConfig | None:
    """Build OtelConfig from config.yaml + env var overrides. Returns None if no endpoint."""
    config = HookConfig.load_from_repo(cwd)
    endpoint = config.otel.endpoint if config and config.otel else None
    auth_token = config.otel.auth_token if config and config.otel else None

    # Env vars override config.yaml (set by session start from k8s secrets)
    endpoint = os.environ.get("DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT", endpoint)
    auth_token = os.environ.get("DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN", auth_token)

    if not endpoint:
        return None
    return OtelConfig(endpoint=endpoint, auth_token=auth_token)


def _init_otel(cwd: Path) -> None:
    """Initialize OTEL from config.yaml + env vars. No-op on failure."""
    try:
        otel_config = _load_otel_config(cwd)
        if otel_config:
            from devinfra.claude import otel

            otel.init_from_config(otel_config)
    except Exception:
        pass  # OTEL init is best-effort, don't break hooks


def _emit_output(output: object | None) -> None:
    """Write hook output JSON to stdout if non-None."""
    if output is not None:
        from pydantic import BaseModel

        if isinstance(output, BaseModel):
            sys.stdout.write(output.model_dump_json(by_alias=True))


def main() -> None:
    raw = sys.stdin.read()
    parsed = _adapter.validate_json(raw)

    _init_otel(parsed.cwd if isinstance(parsed.cwd, Path) else Path(parsed.cwd))

    try:
        match parsed:
            case SessionStartHookInput():
                # Lazy import: heavyweight (async, mako, otel)
                from devinfra.claude.session_start import _async_handle

                asyncio.run(_async_handle(parsed))

            case PreToolUseInput():
                from devinfra.claude.pre_tool_use import evaluate as evaluate_pre

                _emit_output(evaluate_pre(parsed))

            case PostToolUseInput():
                from devinfra.claude.post_tool_use import evaluate as evaluate_post

                _emit_output(evaluate_post(parsed))
    except Exception as e:
        print(f"Hook failed ({parsed.hook_event_name}): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
