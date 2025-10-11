Seatbelt Exec MCP Server (macOS sandbox-exec)

Overview
- Location: src/adgn/mcp/seatbelt_exec/server.py
- Server name: seatbelt_exec
- Purpose: execute processes under the macOS seatbelt (sandbox-exec).
  - Stateless: callers must provide a full SBPL policy on each call.
- Platform: macOS-only. The server refuses to instantiate on non‑darwin.

Policy input
- Schema: SBPLPolicy from adgn.seatbelt.model (Pydantic), with validation and extra="forbid".
- Provide `policy: SBPLPolicy` on every call.

Tool (FastMCP)
1) sandbox_exec
   - Input fields:
     - policy: SBPLPolicy (required)
     - argv: list[str] (required; no shell)
     - cwd: str | null (optional)
     - env: {str: str} | null (optional)
     - timeout_ms: int (0 < timeout_ms <= 300_000)
     - trace: bool (default: false)
   - Return (SandboxExecResult):
     - exit_code: int | null (null when timeout=true)
     - timeout: bool
     - duration_ms: int
     - stdout: string or {truncated_text,total_bytes}
     - stderr: string or {truncated_text,total_bytes}
     - trace_text: str | null (present iff trace==true and trace captured)
     - unified_sandbox_denies_text: str | null (disabled by default)
   - Errors:
     - NOT_DARWIN (macOS only)
     - SANDBOX_EXEC_MISSING (sandbox-exec not available on PATH)
     - LAUNCH_ERROR (unexpected failure running the process)
     - TEMPLATE_NOT_FOUND (referenced template does not exist)

No template management tools; server is stateless.

Notes
- Timeout semantics: if timeout_ms elapses, the process is killed and the result returns timeout=true, exit_code=null, empty stdout/stderr.
- stdout/stderr are text only in v1. TODO markers exist in the server to add *_b64 fields when non‑UTF‑8 appears.
- No start/end timestamps are returned; only duration_ms.
- Error handling: FastMCP converts uncaught exceptions into MCP tool errors (`isError=true`). Avoid redundant wrappers; raise `ToolError` with specific codes when needed.
- Runtime container workflow: not required; provide full policy per call.

Resources
- None exposed by this server (stateless).

Development and tests
- Integration tests live at tests/mcp/test_seatbelt_exec_inproc.py
  - Echo happy path
  - Write denied under restrictive policy
  - Timeout behavior
  - CWD and env propagation
- The test suite uses @pytest.mark.requires_sandbox_exec, which implies macOS and checks availability of sandbox-exec on PATH.

Internal impl tips
- Server entry: SeatbeltExecMCP(name, agent_id, persistence) constructs the server; embed via HTTP or run under stdio.
- Execution uses adgn.seatbelt.runner.apopen(...), enforcing timeout and returning text outputs.
- seatbelt runner has collect_unified_sandbox_denies(...) and a shared result tail helper to avoid duplication.
