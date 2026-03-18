"""Unified Claude Code hook entry point.

Thin client that sends all hooks to the hook daemon over UDS. The daemon
handles dispatch, OTEL, and session start setup. If the daemon is unreachable,
the client starts a new one automatically.
"""

import os
import sys
import traceback
from pathlib import Path

from pydantic import TypeAdapter

from devinfra.claude.claude_api.hooks.dispatch_input import AnyHookInput
from devinfra.claude.hook_daemon.client import call_daemon
from devinfra.claude.settings import HookSettings

_adapter: TypeAdapter[AnyHookInput] = TypeAdapter(AnyHookInput)

# Claude Code stores per-session data at ~/.claude/session-env/<session_id>/
_SESSION_ENV_BASE = Path.home() / ".claude" / "session-env"


def main() -> None:
    raw = sys.stdin.buffer.read()
    parsed = _adapter.validate_json(raw)

    session_dir = _SESSION_ENV_BASE / parsed.session_id
    settings = HookSettings(session_dir=session_dir)

    result = call_daemon(parsed, dict(os.environ), settings)
    if result is not None:
        if result.output is not None:
            # exclude_none: Zod .optional() accepts undefined (absent) but NOT null.
            # Pydantic emits None as null by default; exclude_none omits those fields.
            sys.stdout.write(result.output.model_dump_json(by_alias=True, exclude_none=True))
    else:
        print("ERROR: hook daemon unavailable", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Hook dispatch failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
