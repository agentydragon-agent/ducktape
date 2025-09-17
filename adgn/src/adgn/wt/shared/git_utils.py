from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import subprocess


def build_sanitized_git_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    e = dict(os.environ if env is None else env)
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    e.setdefault("GIT_CONFIG_GLOBAL", "/dev/null")
    e.setdefault("GIT_CONFIG_SYSTEM", "/dev/null")
    e.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return e


def git_run(
    args: Sequence[str | os.PathLike[str]],
    cwd: Path | str,
    check: bool = True,
    capture_output: bool = True,
    env: Mapping[str, str] | None = None,
    input: bytes | None = None,
) -> subprocess.CompletedProcess:
    cmd: list[str | os.PathLike[str]] = ["git", "-c", "core.hooksPath=", *args]
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        env=build_sanitized_git_env(env),
        input=input,
    )
