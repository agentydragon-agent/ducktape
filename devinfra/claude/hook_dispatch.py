"""Unified Claude Code hook entry point.

Reads JSON from stdin, parses into a discriminated union (AnyHookInput),
then dispatches to the appropriate handler via match/isinstance.
Initializes OTEL tracing from .claude_hooks/config.yaml if available.
Uses lazy imports for handler modules (mako, kubernetes, etc.) so lightweight
hooks like PreToolUse and PostToolUse don't pay for those imports.
"""

import asyncio
import logging
import sys
import traceback
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from devinfra.claude import otel
from devinfra.claude.claude_api.hooks.dispatch_input import AnyHookInput
from devinfra.claude.claude_api.hooks.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.hooks.pre_tool_use import PreToolUseInput
from devinfra.claude.claude_api.hooks.session_start import SessionStartHookInput
from devinfra.claude.hook_config import HookConfig

logger = logging.getLogger(__name__)

_adapter: TypeAdapter[AnyHookInput] = TypeAdapter(AnyHookInput)


def main() -> None:
    raw = sys.stdin.read()
    parsed = _adapter.validate_json(raw)
    cwd = Path(parsed.cwd)

    # Load config and init OTEL (best-effort, don't break hooks)
    config = None
    try:
        config = HookConfig.load_from_repo(cwd)
        if config and config.otel and config.otel.endpoint:
            otel.init_from_config(config.otel)
    except Exception:
        logger.debug("Failed to load config or init OTEL", exc_info=True)

    # TODO: Load HookSettings at dispatch level and pass to handlers, so all hook
    # types can access shared settings. Currently deferred because HookSettings imports
    # pydantic_settings/platformdirs which would slow down lightweight hooks.
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
