# Progress Log — Jupyter MCP STDIO Guard

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

1. Harden mcp_stdio_protocol for slow-start scenarios
   - Add small backoff loop around read_line_json_fn calls during initialize and tool result
   - Consider bumping default timeout from 20s → 30s
2. Expand test coverage
   - Multi-call sequence (append, execute, verify state)
   - Error-path tests (invalid tool name, bad args)
3. macOS seatbelt policy iteration
   - Use --trace-sandbox, collect denials, adjust policy rules incrementally
   - When stable, keep the stricter policy as default
4. CI polish
   - Add ruff hooks config for tests dir if not already enforced
   - Document required binaries and optional deps in README of this package

## Notes

- MCP stdio remains strictly newline-delimited JSON (no extra framing)
- All test env injection goes through fixtures; no os.environ mutations in tests
- Token redaction/log sensitivity: avoid copying TOKEN into shared logs
