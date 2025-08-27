# Progress Log — Jupyter MCP STDIO Guard

2025-08-27T19:07:56Z sha=a0b2a54: Split tools validated; MCP handshake debugged; seatbelt policy tightened

- Implemented split: sandboxer (seatbelt MVP), jupyter-mcp-launch (unsandboxed Jupyter + jupyter-mcp-server stdio), jupyter-sandbox-compose (bundle composer from single YAML via stdin).
- MCP stdio protocol confirmed NDJSON (newline-delimited JSON) with protocolVersion 2025-06-18. Fixed a prior framing confusion; initialize → notifications/initialized → tools/list/tool calls verified with scratch/run_probe2.py.
- jupyter_mcp_launch ensured MCP child inherits stdio so tests can speak NDJSON directly to jupyter-mcp-server.
- End-to-end example test now passes: initialize, tools/list, execute code, then attempt a denied write outside workspace.
- Root cause of initial timeouts: macOS seatbelt blocked exec of the kernel venv Python (execvp Operation not permitted). Observed in runtime/jupyter_server.err and reproduced with sandboxer directly.
- Policy fixes (tight but working):
  - No allow_read_all; restrict fs.read_paths to the kernel venv root (and venv/lib) and the composed bundle; write_paths limited to runtime and workspace only.
  - Sandboxer now emits process-exec allow rules for binaries under configured read_paths, enabling python exec without broadening file read to '/'.
  - Kept net.mode=loopback; no outbound allowed.
- YAML hygiene: switched all composer inputs to yaml.safe_dump/safe_load; removed hand-templated YAML blocks in tests.
- Observability workflow used (per docs/DEBUGGING_CATALOG.md & WORKFLOW.md):
  - Jupyter logs: runtime/jupyter_server.err showed kernel restarts and precise seatbelt execvp denial lines.
  - Direct sandboxer repro with the same policy to isolate exec failure.
  - MCP probe (scratch/run_probe2.py) to confirm initialize/tools-list independently of pytest.

Next
- Tighten further by trimming venv read surface to exact binary and site-packages if feasible; turn on seatbelt trace for targeted runs and collect macOS log denials for precise rule deltas.
- Implement Linux bwrap backend in sandboxer; enforce net proxy/allowlist modes.
