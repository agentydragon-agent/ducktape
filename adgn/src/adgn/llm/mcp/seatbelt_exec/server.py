from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict

from adgn.seatbelt.model import SBPLPolicy
from adgn.seatbelt.runner import apopen


SERVER_NAME = "seatbelt_exec"
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class SandboxExecResult(BaseModel):
    """Minimal exec result for sandbox_exec (text outputs only).

    Note: stdout/stderr are UTF-8 decoded with replacement.
    TODO: add *_b64 fields for non-UTF8 payloads when needed.
    """

    exit_code: int | None
    timeout: bool
    duration_ms: int
    stdout_text: str | None = None
    stderr_text: str | None = None
    trace_text: str | None = None

    model_config = ConfigDict(extra="forbid")


def _validate_id(policy_id: str) -> None:
    if not isinstance(policy_id, str) or not _ID_RE.fullmatch(policy_id):
        raise ToolError("invalid policy_id", code="INVALID_ID")


def make_seatbelt_exec_mcp(name: str = SERVER_NAME) -> FastMCP:
    """Create a macOS seatbelt-backed exec MCP server (in-memory policies).

    Tools
    - list_policies() -> list[str]
    - get_policy(policy_id: str) -> SBPLPolicy
    - set_policy(policy_id: str, policy: SBPLPolicy) -> {}
    - delete_policy(policy_id: str) -> {}
    - sandbox_exec(policy_id: str, argv: list[str], cwd?: str, env?: dict[str,str], timeout_secs?: float, trace?: bool)
      -> SandboxExecResult
    """

    # In-memory per-server store, protected by an asyncio lock for concurrent calls
    store: dict[str, SBPLPolicy] = {}
    lock = asyncio.Lock()

    mcp = FastMCP(
        name,
        instructions=(
            "Execute commands via macOS seatbelt (sandbox-exec). Policies are in-memory for the session."
        ),
    )

    @mcp.tool()
    async def list_policies() -> list[str]:
        # No parameters; return sorted listing for stable order
        async with lock:
            return sorted(store.keys())

    @mcp.tool()
    async def get_policy(policy_id: str) -> SBPLPolicy:
        _validate_id(policy_id)
        async with lock:
            if policy_id not in store:
                raise ToolError("policy not found", code="POLICY_NOT_FOUND")
            return store[policy_id]

    @mcp.tool()
    async def set_policy(policy_id: str, policy: SBPLPolicy) -> dict[str, Any]:
        _validate_id(policy_id)
        # SBPLPolicy is already validated by FastMCP/Pydantic
        async with lock:
            store[policy_id] = policy
        return {}

    @mcp.tool()
    async def delete_policy(policy_id: str) -> dict[str, Any]:
        _validate_id(policy_id)
        async with lock:
            if policy_id not in store:
                raise ToolError("policy not found", code="POLICY_NOT_FOUND")
            del store[policy_id]
        return {}

    @mcp.tool()
    async def sandbox_exec(
        policy_id: str,
        argv: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_secs: float | None = None,
        trace: bool = False,
    ) -> SandboxExecResult:
        # Platform precheck
        if sys.platform != "darwin":
            raise ToolError("sandbox available only on macOS", code="NOT_DARWIN")

        _validate_id(policy_id)
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(a, str) for a in argv)
        ):
            raise ToolError("argv must be a non-empty list[str]", code="INVALID_ARGV")
        cwd_path = Path(cwd).resolve() if isinstance(cwd, str) else None

        # Load policy
        async with lock:
            policy = store.get(policy_id)
        if policy is None:
            raise ToolError("policy not found", code="POLICY_NOT_FOUND")

        # Run with apopen so we can enforce timeout and kill if needed
        try:
            async with await apopen(
                argv,
                policy,
                cwd=cwd_path,
                env=env,
                trace=trace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ) as proc:
                start = asyncio.get_event_loop().time()
                try:
                    out_b, err_b = await proc.communicate(timeout=timeout_secs)
                    timed_out = False
                except asyncio.TimeoutError:
                    # Best-effort termination; __aexit__ will also ensure cleanup
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        await proc.wait()
                    except Exception:
                        pass
                    out_b, err_b = b"", b""
                    timed_out = True
                duration_ms = int(
                    round((asyncio.get_event_loop().time() - start) * 1000)
                )

                # Minimal outputs (text only; utf-8 with replacement)
                stdout_text = (
                    out_b.decode("utf-8", errors="replace")
                    if out_b is not None
                    else None
                )
                stderr_text = (
                    err_b.decode("utf-8", errors="replace")
                    if err_b is not None
                    else None
                )

                trace_text: str | None = None
                if trace and proc.trace_file and proc.trace_file.exists():
                    try:
                        trace_text = proc.trace_file.read_text(errors="replace")
                    except Exception:
                        trace_text = None

                return SandboxExecResult(
                    exit_code=(None if timed_out else proc.returncode),
                    timeout=timed_out,
                    duration_ms=duration_ms,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                    trace_text=trace_text,
                )
        except FileNotFoundError as e:
            # sandbox-exec missing
            raise ToolError(str(e), code="SANDBOX_EXEC_MISSING") from e
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(
                "launch error", code="LAUNCH_ERROR", details={"error": str(e)}
            ) from e

    return mcp
