from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path


def build_sanitized_git_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    e = dict(os.environ if env is None else env)
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    e.setdefault("GIT_CONFIG_GLOBAL", "/dev/null")
    e.setdefault("GIT_CONFIG_SYSTEM", "/dev/null")
    e.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return e


def git_run(  # noqa: PLR0913
    args: list[str],
    cwd: Path | str,
    check: bool = True,
    capture_output: bool = True,
    env: Mapping[str, str] | None = None,
    input: bytes | None = None,
) -> subprocess.CompletedProcess:
    cmd = ["git", "-c", "core.hooksPath=", *args]
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        env=build_sanitized_git_env(env),
        input=input,
    )
