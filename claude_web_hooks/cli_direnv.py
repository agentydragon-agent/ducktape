#!/usr/bin/env python3
"""Session start hook for Claude Code CLI: loads direnv environment.

Does NOT use the claude_hooks package - parses hook I/O directly.

TODO: Migrate to using claude_hooks package for typed hook input parsing
once we get the wiring working (Pydantic models, proper error handling, etc.)

TODO: Rename claude_web_hooks to something more neutral (e.g., claude_session_hooks),
or split web/local CLI hooks into separate packages since CLI is not web.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def find_envrc(start_dir: Path) -> Path | None:
    """Walk up from start_dir to find .envrc file."""
    current = start_dir.resolve()
    while current != current.parent:
        envrc = current / ".envrc"
        if envrc.exists():
            return envrc
        current = current.parent
    return None


def main() -> int:
    # Only run in CLI (not web)
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        return 0

    # Parse hook input from stdin (simple JSON parsing, no claude_hooks dependency)
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("direnv: failed to parse hook input", file=sys.stderr)
        return 2

    cwd = Path(hook_input.get("cwd", Path.cwd()))

    # Find .envrc (walk up from cwd)
    envrc = find_envrc(cwd)
    if not envrc:
        # Fallback to ducktape root
        ducktape_envrc = Path.home() / "code" / "ducktape" / ".envrc"
        if ducktape_envrc.exists():
            envrc = ducktape_envrc
        else:
            return 0  # No .envrc to load

    # Print direnv-style loading banner
    print(f"direnv: loading {envrc}")

    # Use direnv to export the environment
    try:
        result = subprocess.run(
            ["direnv", "export", "bash"], check=False, cwd=envrc.parent, capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        print("direnv: not installed, skipping", file=sys.stderr)
        return 0
    except subprocess.TimeoutExpired:
        print("direnv: export timed out", file=sys.stderr)
        return 2

    if result.returncode != 0:
        print(f"direnv: export failed: {result.stderr}", file=sys.stderr)
        return 2

    # direnv export bash outputs shell commands like:
    # export VAR="value"; export VAR2="value2";
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        print("direnv: CLAUDE_ENV_FILE not available", file=sys.stderr)
        return 0

    # Write the exports to CLAUDE_ENV_FILE
    if result.stdout.strip():
        Path(env_file).write_text(result.stdout)
        # Print direnv-style export banner (summarize changes)
        exports = []
        for part in result.stdout.split("export "):
            if "=" in part:
                var = part.split("=")[0].strip()
                if var:
                    exports.append(f"+{var}")
        if exports:
            print(
                f"direnv: export {' '.join(exports[:5])}"
                + (f" ... (+{len(exports) - 5} more)" if len(exports) > 5 else "")
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
