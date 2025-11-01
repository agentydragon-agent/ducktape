from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

import yaml


class CommandError(RuntimeError):
    """Raised when an external command fails."""


class CompletedProcess:
    """Async-friendly analogue of subprocess.CompletedProcess."""

    def __init__(
        self,
        args: Iterable[str],
        returncode: int,
        stdout: str | bytes,
        stderr: str | bytes,
    ) -> None:
        self.args = list(args)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


async def run_command(
    cmd: Iterable[str],
    *,
    input_data: bytes | None = None,
    check: bool = True,
    cwd: Path | None = None,
    text: bool = True,
) -> CompletedProcess:
    """Run a subprocess asynchronously, raising CommandError on failure when check is true."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if input_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
    )
    stdout, stderr = await process.communicate(input_data)
    if text:
        stdout_decoded: str | bytes = (
            stdout.decode("utf-8", errors="replace") if stdout else ""
        )
        stderr_decoded: str | bytes = (
            stderr.decode("utf-8", errors="replace") if stderr else ""
        )
    else:
        stdout_decoded = stdout
        stderr_decoded = stderr
    if check and process.returncode != 0:
        raise CommandError(
            f"Command {' '.join(cmd)} failed with exit code {process.returncode}\n"
            f"stdout:\n{stdout_decoded}\n\nstderr:\n{stderr_decoded}"
        )
    return CompletedProcess(cmd, process.returncode, stdout_decoded, stderr_decoded)


def merge_dict(dst: dict[str, object], src: dict[str, object]) -> None:
    """Recursively merge src into dst."""
    for key, value in src.items():
        current = dst.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merge_dict(current, value)
        else:
            dst[key] = value


def dump_yaml(obj: dict[str, object]) -> bytes:
    """Serialize an object to YAML bytes."""
    return yaml.safe_dump(obj, sort_keys=False).encode("utf-8")
