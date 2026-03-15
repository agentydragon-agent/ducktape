"""Unified Claude Code hook entry point.

Reads JSON from stdin, parses into a discriminated union (AnyHookInput),
then dispatches to the appropriate handler via match/isinstance.
Initializes OTEL tracing from .claude_hooks/config.yaml if available.
Uses lazy imports to avoid loading heavy dependencies (mako, asyncio)
for lightweight hooks like PreToolUse and PostToolUse.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from pydantic import TypeAdapter

from devinfra.claude.claude_api.hook_dispatch_input import AnyHookInput
from devinfra.claude.claude_api.hook_input import HookInput as SessionStartInput
from devinfra.claude.claude_api.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.pre_tool_use import PreToolUseInput
from devinfra.claude.hook_config import OtelConfig, load_repo_config

_adapter: TypeAdapter[AnyHookInput] = TypeAdapter(AnyHookInput)


def _init_otel(cwd: str) -> None:
    """Initialize OTEL from config.yaml + env vars. No-op on failure.

    Reads endpoint from config.yaml, auth_token from
    DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN env var (set by session start
    from k8s secrets). Env vars override config.yaml values.
    """
    try:
        config = load_repo_config(Path(cwd))
        endpoint = config.otel.endpoint if config and config.otel else None
        auth_token = config.otel.auth_token if config and config.otel else None

        # Env vars override config.yaml (set by session start from k8s secrets)
        endpoint = os.environ.get("DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT", endpoint)
        auth_token = os.environ.get("DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN", auth_token)

        if endpoint:
            from devinfra.claude import otel

            otel.init_from_config(OtelConfig(endpoint=endpoint, auth_token=auth_token))
    except Exception:
        pass  # OTEL init is best-effort, don't break hooks


def main() -> None:
    raw = sys.stdin.read()

    try:
        parsed = _adapter.validate_json(raw)
    except Exception:
        # Unknown or malformed hook event — silently exit
        return

    _init_otel(str(parsed.cwd))

    try:
        match parsed:
            case SessionStartInput():
                # Lazy import: heavyweight (async, mako, otel)
                from devinfra.claude.session_start import handle_session_start

                handle_session_start(parsed)

            case PreToolUseInput():
                from devinfra.claude.pre_tool_use import evaluate as evaluate_pre

                pre_result = evaluate_pre(parsed)
                if pre_result is not None:
                    sys.stdout.write(pre_result.model_dump_json(by_alias=True))

            case PostToolUseInput():
                from devinfra.claude.post_tool_use import evaluate as evaluate_post

                post_result = evaluate_post(parsed)
                if post_result is not None:
                    sys.stdout.write(post_result.model_dump_json(by_alias=True))
    except Exception as e:
        print(f"Hook failed ({parsed.hook_event_name}): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
