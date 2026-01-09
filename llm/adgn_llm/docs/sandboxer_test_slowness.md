# Sandboxer test slowness: findings and root causes

This note documents why the sandboxed_jupyter_mcp test suite is slow and what contributes most to wall‐clock time, based on local runs with pytest --durations and per‑file/per‑test timing.

## Summary

- The primary causes of slowness are:
  1. One‑time “control venv” bootstrap that installs a large Jupyter + MCP stack inside a temporary virtualenv during test setup.
  2. Jupyter server startup and health check (port readiness can take ~20–30s on cold starts).
  3. MCP stdio handshake + tool call timeouts that run close to their caps on failure paths.
- No per‑test 30s “hangs” were found outside sandboxer; slowness is concentrated in sandboxer suite setup and calls.
- Running sandboxer tests together shows the slowest durations in setup/call phases rather than long function bodies.

## Measurements

Command:

- direnv exec "$(pwd)" uv run pytest tests/mcp/sandboxed_jupyter_mcp --durations=15 -q

Slowest durations observed:

- 21.84s setup test_kernel_sandbox_end_to_end.py::test_network_modes_http_boundary[loopback]
- 20.05s call test_wrapper_unsandbox_smoke.py::test_wrapper_unsandbox_initialize_and_hello
- 16.09s call test_unsandbox_smoke.py::test_unsandbox_initialize_and_hello
- ~0.16–1.8s for typical sandboxed exec tests (echo/venv/python/trivial)

When a subset is run, these durations are reproducible. Running non‑sandbox suites with a 30s per‑file watchdog showed no hangs and quick completions.

## What’s slow (by component)

1. Session‑scoped control venv bootstrap (tests/mcp/sandboxed_jupyter_mcp/conftest.py)

   - Fixture: `_bootstrap_control_venv_and_require_tools(scope="session", autouse=True)`
   - Actions on cold start:
     - python3 -m venv <tmp>/control_venv
     - Upgrade pip/wheel in that venv
     - pip install jupyter‑server, jupyter‑core, jupyter‑mcp‑server, jupyter‑server‑ydoc, jupyter‑collaboration, pycrdt‑websocket (and their large dependency set)
   - Evidence: test logs repeatedly show pip upgrading to pip 25.2 and installing dozens of packages during setup, adding ~10–20s cold start overhead.

2. Jupyter server startup

   - Fixture: launch_jupyter_server
   - Waits up to 30s for the port to become ready (tight .1–.5s polling loop) before yielding to tests.
   - On cold starts, we observed ~20s before server responded on loopback.

3. MCP stdio handshake + tool calls
   - Helpers: mcp_stdio_protocol / mcp_call_tool
   - initialize wait: up to 20–25s; tools/call wait: up to 60s.
   - On successful runs, these complete quickly; on failing runs they approach the timeout, inflating wall time.

## Not cross‑test interference

- Running the sandboxer suite together produced failures but not timeouts; rerunning failing tests in isolation shows the same failures (not order‑dependent flakiness).
- Non‑sandbox suites did not exhibit per‑test hangs; the full‑suite timeout earlier was due to aggregate duration rather than a single test stuck.

## Why now (environment)

- macOS (Darwin) with sandbox‑exec and unified logging enabled.
- direnv + devenv environment; per‑session tmpdir used for control venv under pytest tmp_path_factory.
- No pre‑warmed cache for the control venv; installs happen inside test setup.

## Recommendations (to reduce wall‑clock time)

1. Pre‑warm the control venv (dev + CI)

   - Create once and reuse via SJ_TEST_CONTROL_BIN to avoid per‑session install:

     ```bash
     python3 -m venv .tmp/control_venv
     .tmp/control_venv/bin/pip install -U pip wheel \
       jupyter-server jupyter-core jupyter-mcp-server \
       jupyter-server-ydoc jupyter-collaboration pycrdt-websocket
     export SJ_TEST_CONTROL_BIN="$(pwd)/.tmp/control_venv/bin"
     pytest -q tests/mcp/sandboxed_jupyter_mcp
     ```

   - In conftest.py, `_bootstrap_control_venv_and_require_tools` already respects `PATH`; add a fast path that uses `SJ_TEST_CONTROL_BIN` if set and valid to skip install.

2. Reduce Jupyter startup time where acceptable

   - If specific tests don’t need collaboration/ydoc, run a leaner server (fewer extensions) to shorten cold start.
   - Consider marking server‑heavy tests as slower and running them in a separate CI job (parallelize).

3. Fail faster on known failure paths

   - Lower initialize/tool call timeouts in tests that are expected to fail quickly or parametrize separate “smoke” cases with shorter timeouts.
   - Example: use init_timeout=10s for smoke, call_timeout=15–30s, unless a test explicitly needs more.

4. Cache pip wheels in CI
   - Enable a pip cache for the control venv installation steps so that cold starts are faster (e.g., use a shared wheel cache dir).

## Actionable TODOs (make it fast and explicit)

- Control venv prewarm and reuse

  - [ ] Teach `tests/mcp/sandboxed_jupyter_mcp/conftest.py::_bootstrap_control_venv_and_require_tools` to honor `SJ_TEST_CONTROL_BIN` if set and points to a bin dir containing jupyter and jupyter-mcp-server; skip creation/install.
    - Acceptance: cold local run with SJ_TEST_CONTROL_BIN set does not run pip and suite setup < 2s.
  - [ ] Provide a simple helper (make target or script) to create .tmp/control_venv and export SJ_TEST_CONTROL_BIN; document the exact commands below.
    - Acceptance: helper finishes < 1 min on warm cache and is documented where devs look.

- CI pip/wheel cache

  - [ ] Configure pip cache in CI for the control venv install step (e.g., set PIP_CACHE_DIR and/or use pip --cache-dir).
    - Acceptance: repeat CI installs reuse cache and reduce cold-start install time by ≥50%.

- Shorter timeouts for smoke paths

  - [ ] Parameterize init_timeout/call_timeout via fixtures; mark “smoke” tests with shorter defaults (init ≤ 10s, call ≤ 30s) and allow overrides per test.
    - Acceptance: failing smoke tests finish in ≤ 30s wall time.

- Lean Jupyter server for non-collab tests

  - [ ] Extend launch_jupyter_server to support a “lean” mode without collaboration/ydoc when not needed; mark collab-required tests with @pytest.mark.collab to keep full stack there.
    - Acceptance: lean tests reach ready state in ≤ 5s on warm start locally.

- Labeling/gating

  - [ ] Mark heavy tests with @pytest.mark.sandboxer and/or @pytest.mark.slow; keep a small @pytest.mark.smoke subset runnable by default.
  - [ ] Maintain the suite-level --run-sandboxer opt-in, and run smoke by default without it; ensure -rs is recommended so skip reasons are visible.
    - Acceptance: pytest -m "not slow" -k sandboxed_jupyter_mcp completes within target local time budget.

- Parallelize in CI

  - [ ] Move sandboxed_jupyter_mcp into its own CI job (optional or triggered-by-changes/nightly) so it doesn’t gate normal PR runs.
    - Acceptance: main CI pipeline excludes sandboxer by default; dedicated job runs in parallel.

- Fix functional failures (removes timeout inflation from retries)

  - [ ] `test_sandboxer_compose.py::test_fs_write_paths_expand_to_params_and_dirs` — implement/fix param expansion for `WP_*`; add targeted unit coverage for compose output.
  - [ ] `test_sandboxer_compose.py::test_fs_read_paths_expand_to_params_and_dirs` — implement/fix param expansion for `RP_*`.
  - [ ] `test_sandboxer_narrow.py::test_sandboxer_yes_hello_world_narrow` — investigate policy deny (exit 250); ensure seatbelt.trace.log populated; fix policy or expectations so echo=0.
  - [ ] `test_wrapper_unsandbox_smoke.py::test_wrapper_unsandbox_initialize_and_hello` — ensure `SJ_TEST_CONTROL_BIN` is honored; debug Jupyter + MCP stdio logs; make initialize succeed in < 3s.

- Developer ergonomics
  - [ ] Add a short “How to run sandboxer” snippet here and in adgn_llm/CLAUDE.md: prewarm control venv, export SJ_TEST_CONTROL_BIN, and pass --run-sandboxer; recommend -rs to show skip reasons.

## Appendix: failing tests (functional issues to resolve)

- test_sandboxer_compose.py::test_fs_write_paths_expand_to_params_and_dirs — expected (param "WP_0") not present in composed policy output.
- test_sandboxer_compose.py::test_fs_read_paths_expand_to_params_and_dirs — expected (param "RP_0") not present.
- test_sandboxer_narrow.py::test_sandboxer_yes_hello_world_narrow — sandboxed echo returns 250 (policy denies?); seatbelt.trace.log is empty/tiny in captured output.
- test_wrapper_unsandbox_smoke.py::test_wrapper_unsandbox_initialize_and_hello — initialize failed: None (no stdio result); check SJ_TEST_CONTROL_BIN env, jupyter logs tails, and MCP stdio logs.

These are failures, not slowness per se, but they inflate wall time by running to upper timeouts.

## TL;DR

- Main cost = cold start install + server boot + long failure timeouts.
- Pre‑warm the control venv and reuse it; reduce server features where possible; shorten timeouts on smoke tests; parallelize the heavy suite in CI.
