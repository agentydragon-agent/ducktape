# CLAUDE.md

This file provides guidance to AI agents when working with code in the `adgn` package.
It explains environment setup (direnv + devenv), how to run tests, lint, and the high‑level module layout.

## Environment and setup (direnv + devenv)
- Requirements: Nix + devenv, direnv (recommended), Python 3.11+.
- First time in this directory:
  - cd /Users/mpokorny/code/ducktape/adgn
  - direnv allow
  - This loads .envrc → devenv, creates a Python 3.11 venv, and installs the package in editable mode with dev extras ([project.optional-dependencies].dev).
- Re-entering the shell later: just cd into adgn; direnv will activate the same environment.
- How to tell if direnv is active (and which env):
  - `direnv status` → shows current `.envrc` and whether it’s loaded
  - `echo "$VIRTUAL_ENV"` → should contain …/adgn/.devenv/state/venv
  - `which python` → should resolve to …/adgn/.devenv/state/venv/bin/python
  - You’ll also see `direnv: loading/unloading` when entering/leaving the directory
- Raw commands vs prefixing:
  - When direnv is active, devenv puts dev tools on PATH automatically — run tools directly: pytest, ruff check ., pre-commit run -a, rspcache, wt, etc. (no prefix needed inside adgn/)
  - When running from outside the directory or in scripts, prefix with: `direnv exec adgn <command>`
- Refresh the environment after edits:
  - devenv.nix/.envrc changes → direnv reload
  - pyproject.toml dependency changes → direnv reload (the shell will reinstall dev extras on entry); if needed: direnv exec adgn python -m pip install -e '.[dev]'

## Common commands
- Run all tests (pytest discovery is configured for adgn/tests):
  - from repo root: `direnv exec adgn pytest adgn/tests`
  - or from adgn/: `pytest tests`
  - Note: parallel execution via `pytest-xdist` enabled by default (see Pytest configuration below).
- Run a single test file or test: `pytest tests/tana_export/test_convert.py::test_node_export`
- Lint/format (ruff): `ruff format .`, `ruff check . --fix`
- Pre-commit (optional in this subpackage):
  - `pre-commit install`
  - `pre-commit run -a`
- Install optional extras (example: GNOME console script deps):
  - `python -m pip install -e '.[gnome]'`

## Console scripts
- switch_gnome_terminal_profile → adgn.gnome.switch_gnome_terminal_profile:run
- rspcache → adgn.rspcache.cli:main
- wt → adgn.wt.cli:main
- wt-install → adgn.wt.shell.install:main

## Pytest configuration (from pyproject.toml)
- timeout = 30; timeout_method = "thread" (pytest-timeout)
- asyncio_mode = "auto" (pytest-asyncio)
- testpaths = ["tests"]
- addopts (defaults applied automatically):
  - -n=auto (pytest-xdist parallelism)
  - -v, --tb=short, --strict-markers, --disable-warnings, --durations=25
- markers:
  - slow, integration, unit, shell, asyncio, real_github (real network/GitHub)
- env (pytest-env ensures hermetic git by default):
  - GIT_CONFIG_NOSYSTEM=1, GIT_CONFIG_GLOBAL=/dev/null

## High‑level architecture
- Packaging (pyproject.toml)
  - name: adgn; requires-python: ">=3.11"; src-layout under adgn/src
  - Dev extras include pytest, pytest-asyncio, pytest-timeout, pytest-xdist, ruff, pre-commit
  - Optional extras:
    - gnome: absl-py, dbus-python, PyGObject (large system deps; install only when needed)
- Selected modules and domains
  - Tana export (src/adgn/tana_export/)
    - convert.py: Export Tana JSON dump to Markdown or TanaPaste text (export_node_as_tanapaste, CLI)
    - export_node_subset.py: Export a single node with dependency tracking and produce a subset JSON
    - materialize_searches.py: Inspect and materialize Tana search nodes, compare stored vs materialized
    - tana_lib/: Pydantic models and helpers for traversing/inspecting node trees (models.py, query.py, search_parser.py, search_materializer.py, filters.py, ...)
  - Response cache (src/adgn/rspcache/)
    - responses_db.py: Lightweight response store; CLI at adgn.rspcache.cli:main (entry point: rspcache)
  - Worktree tools (src/adgn/wt/)
    - CLI and plugin system: adgn.wt.cli, adgn.wt.plugins, adgn.wt.demo_plugin (entry point: wt)
    - Server/services: wt.server.*, handlers (PR/status/worktree), registry and discovery
    - Client: wt.client.* (formatting, shell utils, handlers)
    - Shared/types: wt.shared.* (configuration, constants, models, protocol)
    - Purpose: Manage git worktrees and status, integrate with GitHub, and provide a local server/CLI with plugin hooks
- Tests and data
  - Tests live under repo-root tests/, mirroring src structure
    - tests/tana_export/test_convert.py → verifies Markdown/TanaPaste outputs using fixture JSON
    - tests/wt/... includes unit, integration, and e2e coverage for worktree flows and GitHub display

## Notes and caveats
- GNOME console script dependencies require system libraries and are intentionally not part of the default install; use the [gnome] extra if you need that tool.
- Some `tana_lib` modules import helpers lazily to avoid circular imports (accepted pattern here).
- Tests marked `real_github` talk to real GitHub/network; run them explicitly when needed.

## LLM (adgn.llm) quickstart and module map

MiniCodex (CLI + local UI)
- REPL: adgn-mini-codex run
- UI server: adgn-mini-codex serve (opens WS UI at http://127.0.0.1:8765/)
- Dev: adgn-mini-codex dev (starts backend + Vite HMR; auto-picks free ports)
- Model/system defaults: --model (OPENAI_MODEL or o4-mini), --system (SYSTEM_INSTRUCTIONS)
- MCP configuration:
  - Baseline: if present, ./.mcp.json in CWD is always loaded first
  - --mcp-config /path/extra.json (repeatable): merge additional .mcp.json files; later files override earlier keys.
  - In-proc servers via .mcp.json: use transport: "inproc" with either:
    - server: a FastMCP instance (Python-only wiring), or
    - factory: dotted path "pkg.mod:make_server" (or "pkg.mod.make_server"), plus optional args/kwargs
    Example file at src/adgn/agent/example.mcp.json wires the seatbelt exec MCP in-process.
- Behavior:
  - On connect, server emits accepted followed by a Snapshot; Snapshot includes MCP server names and any transcript from the current process.
  - Approvals are protocol‑native: approval_pending → approval_decision (approve | deny_continue | deny_abort); server maps them to handler decisions.
  - Serve constructs the agent and MCP on the uvicorn loop (app.state.agent_factory) to avoid cross‑loop hangs.
- UI dev/build:
  - Dev (recommended): adgn-mini-codex dev — starts FastAPI backend and Vite (frontend HMR), picks free ports; Vite proxies /ws (and /transcript)
  - Split dev: adgn-mini-codex serve (backend) + npm --prefix src/adgn/agent/web run dev (optionally export VITE_BACKEND_ORIGIN=http://127.0.0.1:8765)
  - Build UI (REQUIRED before running serve):
    ```bash
    npm --prefix src/adgn/agent/web install
    npm --prefix src/adgn/agent/web run build
    ```
  - Assets are published to src/adgn/agent/server/static/web; FastAPI serves /static/web and /assets
  - Note: The UI assets MUST be built before running `adgn-mini-codex serve` or you'll get a RuntimeError about missing static directory
  - Layout: full‑page chat (left, bottom‑docked composer) + sidebar (WS status dot, run status, servers, approvals)
  - Snapshot on hello restores transcript in the UI on reload
  - Client WS diagnostics surface onerror/onclose
- Troubleshooting:
  - If some MCP servers fail to start, serve continues with the rest; check terminal logs for the failing server names and exceptions
  - Server logs include “WS OUT” for every payload; serve runs uvicorn with log_level=debug
  - Hard refresh after rebuilding UI assets

This section documents the LLM toolkit that was migrated from llm/adgn_llm into the adgn package under src/adgn/llm.

Environment
- Use the same adgn direnv/devenv. No separate uv env is required.
- OPENAI_API_KEY and any provider credentials should be exported before running tools/tests.

Core CLIs (installed via adgn [project.scripts])
- adgn-llm-edit → adgn.llm.llm_edit:app
- adgn-sysrw → adgn.llm.sysrw.cli:app
- adgn-properties → adgn.props.cli:main (and adgn-properties2 → adgn.props.cli_app.main:app)
- git-commit-ai → adgn.git_commit_ai.cli:main
- sandbox-jupyter → adgn.mcp.sandboxed_jupyter.wrapper:main
- adgn-sandboxer, adgn-mcp-* as needed by workflows

Specimen inspection (properties)
- Schema (Pydantic source of truth):
  - @src/adgn/llm/properties/models/specimen.py
  - @src/adgn/llm/properties/models/issue.py
- Loader/hydration: @src/adgn/llm/properties/specimen_registry.py
- Example: adgn-properties specimen-shell <specimen-id>

Testing
- LLM tests live under repo-root: adgn/tests/llm/** (mirrors src/adgn/llm/**)
- Typical invocations:
  - `direnv exec adgn pytest -q -m "not live_llm"`
  - `direnv exec adgn pytest -q -m "not live_llm" -k "not sandboxed_jupyter"`

Quick usage examples
- System rewriter (Node required for apply step):
  - `adgn-sysrw run <path-to-template>`
  - `adgn-sysrw extract --source ccr | crush | …`
  - `adgn-sysrw compare <runs/ts>`
- LLM edit CLI: `adgn-llm-edit --help`
- Search for property violations: `adgn-properties find /path/to/repo "all files under internal/app/**"`

High-level module map
- adgn.llm.sysrw — system prompt rewrite/eval
- adgn.llm.llm_edit — local code/text edit helper
- adgn.props — property definitions + CLI, data under src/adgn/llm/properties/specimens/** and prompts/**
- adgn.inop — instruction optimizer (runners/engine)
- adgn.mcp — MCP utilities/launchers (e.g., sandboxed Jupyter MCP)
- adgn.agent — OpenAI client helpers and agent loop

Notes
- Test/specimen data in src/adgn/llm/properties/specimens/** are excluded from linting/test discovery where configured.
- The system rewriter’s Node script validates inputs and fails fast if Node or required helpers are missing.

@instructions/jsonnet_authoring.md
@instructions/fastmcp_pydantic.md
@instructions/fastmcp_exceptions.md
