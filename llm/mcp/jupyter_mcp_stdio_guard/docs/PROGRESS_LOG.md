# Progress Log — Jupyter MCP STDIO Guard

- Timestamp: 2025-08-18T08:52:00Z
- Repo SHA: 3a4c8c2

## Update

- Standardized CLI name everywhere: `sandbox-jupyter-mcp`
  - Updated README, docs, and helper scripts
  - STDIO mode: `sandbox-jupyter-mcp --stdio-server`

---

- Timestamp: 2025-08-18T08:46:38Z
- Repo SHA: 3a4c8c2

## Update

- Wrapper unsandbox smoke test: PASS
- macOS user-level seatbelt test: PASS (with current permissive behavior)
- Ladder status:
  1) Manual unsandbox: PASS (earlier)
  2) Wrapper --no-kernel-sandbox: PASS
  3) Seatbelt path in test: PASS (baseline; ready to iterate policy tightening)

Next: iterate seatbelt policy to tighten permissions while keeping tests green. Document denials and rule changes per run.

---

- Timestamp: 2025-08-18T08:40:36Z
- Repo SHA: 72d3810

## Update

- Unsandbox smoke test passes after hardening protocol and server start:
  - launch_jupyter_server now waits for port readiness before yielding
  - mcp_stdio_protocol uses a read-until loop with short polls and larger total timeouts (init=20s, call=30s)
- Manual unsandbox run validated via scratch script (hello world observed in result)

---

- Timestamp: 2025-08-18T08:28:48Z
- Repo SHA: ada52cf

## Current State

- DRY test/fixture architecture in place:
  - launch_proc: unified subprocess context manager with env injection
  - launch_jupyter_server: context-managed Jupyter with port-wait and log files
  - mcp_stdio_protocol: initialize → notifications/initialized → tools/call
  - Shared helpers: pick_free_port, gen_token, wait_port, pkg_src_env_update, send/read JSON
  - Centralized required binary checks; macOS RTC via fixture
- Tests refactored to orchestration-only:
  - test_unsandbox_smoke.py (direct jupyter-mcp-server)
  - test_wrapper_unsandbox_smoke.py (wrapper, kernel unsandboxed)
  - test_macos_user_level.py (wrapper, macOS seatbelt path)
- Manual tmux workflow documented in docs/TMUX_MANUAL_TESTING.md with helper scripts under scripts/.

## Works

- Fixtures function and are shared across all tests
- Jupyter server fixture reliably waits for port before yielding
- Wrapper and direct MCP command lines standardized and available as scripts
- Manual tmux recipe provides end-to-end steps (init → notify → tool call)

## Issues / Flakes Observed

- Unsandbox smoke test timed out once while waiting for tools/call result; likely due to startup latency on fresh Jupyter runtime. Port-wait added to server fixture; may still need a small retry/backoff in protocol reads.
- macOS seatbelt flow depends on RTC deps (jupyter-collaboration, pycrdt) and seatbelt policy. Manual iteration recommended to resolve denials before relying on automated runs.

## Next Steps

1. Tighten seatbelt policy gradually while ensuring tests stay green
2. Expand test coverage (multi-call, error paths)
3. CI polish and ruff hooks for tests dir

## Notes

- MCP stdio remains strictly newline-delimited JSON (no extra framing)
- All test env injection goes through fixtures; no os.environ mutations in tests
- Token redaction/log sensitivity: avoid copying TOKEN into shared logs
