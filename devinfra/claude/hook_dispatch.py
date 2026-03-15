"""Unified Claude Code hook entry point.

Reads JSON from stdin, parses into a discriminated union (AnyHookInput),
then dispatches to the appropriate handler via match/isinstance.
Initializes OTEL tracing from .claude_hooks/config.yaml if available.
Uses lazy imports to avoid loading heavy dependencies (mako, asyncio)
for lightweight hooks like PreToolUse and PostToolUse.
"""

import asyncio
import sys
import traceback
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from devinfra.claude import otel
from devinfra.claude.claude_api.hook_dispatch_input import AnyHookInput
from devinfra.claude.claude_api.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.pre_tool_use import PreToolUseInput
from devinfra.claude.claude_api.session_start_input import SessionStartHookInput
from devinfra.claude.hook_config import HookConfig

_adapter: TypeAdapter[AnyHookInput] = TypeAdapter(AnyHookInput)


def main() -> None:
    raw = sys.stdin.read()
    parsed = _adapter.validate_json(raw)
    cwd = parsed.cwd if isinstance(parsed.cwd, Path) else Path(parsed.cwd)

    # Load config and init OTEL (best-effort, don't break hooks)
    config = None
    try:
        config = HookConfig.load_from_repo(cwd)
        if config and config.otel and config.otel.endpoint:
            otel.init_from_config(config.otel)
    except Exception:
        pass

    try:
        output: BaseModel | None = None
        match parsed:
            case SessionStartHookInput():
                from devinfra.claude.session_start import _async_handle

                output = asyncio.run(_async_handle(parsed))

            case PreToolUseInput():
                from devinfra.claude.pre_tool_use import evaluate as evaluate_pre

                output = evaluate_pre(parsed)

            case PostToolUseInput():
                from devinfra.claude.post_tool_use import evaluate as evaluate_post

                output = evaluate_post(parsed)

        if output is not None:
            sys.stdout.write(output.model_dump_json(by_alias=True))
    except Exception as e:
        print(f"Hook failed ({parsed.hook_event_name}): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
