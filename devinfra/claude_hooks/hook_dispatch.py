"""Unified Claude Code hook entry point.

Dispatches to the appropriate handler based on hook_event_name in the JSON input.
Uses lazy imports to avoid loading heavy dependencies (mako, otel, asyncio) for
lightweight hooks like PreToolUse and PostToolUse.
"""

from __future__ import annotations

import io
import json
import sys
import traceback


def main() -> None:
    raw = sys.stdin.read()

    try:
        event = json.loads(raw).get("hook_event_name", "")
    except json.JSONDecodeError:
        return

    # Lazy imports: each handler pulls in different deps.
    # SessionStart is heavyweight (async, mako, otel); others are lightweight.
    if event == "SessionStart":
        from devinfra.claude_hooks.session_start import main as handler
    elif event == "PreToolUse":
        from devinfra.claude_hooks.pre_tool_use import main as handler
    elif event == "PostToolUse":
        from devinfra.claude_hooks.post_tool_use import main as handler
    else:
        return

    # Re-feed stdin since the handler also reads it.
    sys.stdin = io.StringIO(raw)

    try:
        handler()
    except Exception as e:
        print(f"Hook failed ({event}): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
