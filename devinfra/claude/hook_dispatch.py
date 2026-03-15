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
from devinfra.claude.settings import HookSettings

logger = logging.getLogger(__name__)

_adapter: TypeAdapter[AnyHookInput] = TypeAdapter(AnyHookInput)

# Claude Code stores per-session data at ~/.claude/session-env/<session_id>/
_SESSION_ENV_BASE = Path.home() / ".claude" / "session-env"


def main() -> None:
    raw = sys.stdin.read()
    parsed = _adapter.validate_json(raw)
    cwd = Path(parsed.cwd)

    config = HookConfig.load_from_repo(cwd)
    if config and config.otel and config.otel.endpoint:
        otel.init_from_config(config.otel)

    session_dir = _SESSION_ENV_BASE / parsed.session_id

    # TODO: Type output narrower than BaseModel (union of concrete output types).
    try:
        output: BaseModel
        match parsed:
            case SessionStartHookInput():
                from devinfra.claude.session_start import _async_handle

                settings = HookSettings(session_dir=session_dir)
                output = asyncio.run(_async_handle(parsed, settings))

            case PreToolUseInput():
                from devinfra.claude.pre_tool_use import evaluate as evaluate_pre

                output = evaluate_pre(parsed)

            case PostToolUseInput():
                from devinfra.claude.post_tool_use import evaluate as evaluate_post

                output = evaluate_post(parsed)

            case _:
                logger.debug("Unhandled hook event: %s", parsed.hook_event_name)
                return

        sys.stdout.write(output.model_dump_json(by_alias=True))
    except Exception as e:
        print(f"Hook failed ({parsed.hook_event_name}): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
