Seatbelt Exec MCP Server (macOS sandbox-exec)

Overview
- Location: src/adgn/mcp/seatbelt_exec/server.py
- Server name: seatbelt_exec
- Purpose: execute processes under the macOS seatbelt (sandbox-exec). The caller must supply the full sandbox policy on each exec call. No server-side policy storage.
- Platform: execution is macOS-only (NOT_DARWIN error otherwise).

Policy
- Schema: SBPLPolicy from adgn.seatbelt.model (Pydantic), with validation and extra="forbid"
- The policy is provided inline on each sandbox_exec call.

Tool (FastMCP)
1) sandbox_exec
   - Input fields:
     - policy: SBPLPolicy (required)
     - argv: list[str] (required; no shell)
     - cwd: str | null (optional)
     - env: {str: str} | null (optional)
     - timeout_secs: float | null (optional)
     - trace: bool (default: false)
   - Return (SandboxExecResult):
     - exit_code: int | null (null when timeout=true)
     - timeout: bool
     - duration_ms: int
     - stdout_text: str | null (utf‑8 decode with replacement)
     - stderr_text: str | null (utf‑8 decode with replacement)
     - trace_text: str | null (present iff trace==true and trace captured)
     - unified_sandbox_denies_text: str | null (disabled by default)
   - Errors:
     - NOT_DARWIN (macOS only)
     - SANDBOX_EXEC_MISSING (sandbox-exec not available on PATH)
     - LAUNCH_ERROR (unexpected failure running the process)

Notes
- Timeout semantics: if timeout_secs elapses, the process is killed and the result returns timeout=true, exit_code=null, empty stdout/stderr.
- stdout/stderr are text only in v1. TODO markers exist in the server to add *_b64 fields when non‑UTF‑8 appears.
- No start/end timestamps are returned; only duration_ms.

Minimal in-proc usage (Python)

from contextlib import AsyncExitStack
import anyio
from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.mcp.seatbelt_exec.server import make_seatbelt_exec_mcp
from adgn.seatbelt.model import SBPLPolicy, ProcessRule, FileRule, FileOp, Subpath, DefaultBehavior

async def main():
    server = make_seatbelt_exec_mcp()
    spec = make_inproc_slot_spec(server)
    async with AsyncExitStack() as stack:
        slot = await spec.open(stack)
        session = slot.session

        # Create a minimal restrictive policy (allow exec mapping + read)
        policy = SBPLPolicy(
            default_behavior=DefaultBehavior.DENY,
            process=ProcessRule(allow_process_star=True, allow_signal_self=True),
            files=[
                FileRule(op=FileOp.FILE_MAP_EXECUTABLE, filters=[]),
                FileRule(op=FileOp.FILE_READ_STAR, filters=[Subpath(subpath="/")]),
            ],
        )

        # Echo command under sandbox
        res = await session.call_tool(
            name="sandbox_exec",
            arguments={
                "policy": policy.model_dump(),
                "argv": ["/bin/echo", "HELLO"],
                "timeout_secs": 5,
                "trace": False,
            },
        )
        payload = res.structuredContent  # object with keys listed under Return (SandboxExecResult)
        assert payload["exit_code"] == 0 and payload["stdout_text"] == "HELLO\n"

anyio.run(main)

Development and tests
- Integration tests live at tests/mcp/test_seatbelt_exec_inproc.py
  - Echo happy path
  - Write denied under restrictive policy
  - Timeout behavior
  - CWD and env propagation
- The test suite uses @pytest.mark.requires_sandbox_exec, which implies macOS and checks availability of sandbox-exec on PATH.

Internal impl tips
- Server entry: make_seatbelt_exec_mcp() builds a FastMCP server and registers tools.
- Execution uses adgn.seatbelt.runner.apopen(...), enforcing timeout and returning text outputs.
- seatbelt runner has collect_unified_sandbox_denies(...) and a shared result tail helper to avoid duplication.
