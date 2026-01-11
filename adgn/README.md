# adgn

Local tools and libraries for my dev/worktree/LLM workflows.

- Agent CLI (`adgn-agent`)
- MCP servers (Gitea mirror)
- Arg0 virtual CLI utilities
- Testing support

## Environment and setup (direnv + devenv)

- Requirements: Nix + devenv, direnv; Python 3.13+.
- First time here: `cd adgn`, `direnv allow`
  - This loads `.envrc` → devenv, creates a Python venv, and installs `adgn` in editable mode with dev extras.
- Re-entering later: just `cd adgn`; direnv activates the environment.
- Verify environment:
  - `direnv status` shows if `.envrc` is loaded
  - `echo "$VIRTUAL_ENV"` contains `.../adgn/.devenv/state/venv`
  - `which python` resolves to `.../adgn/.devenv/state/venv/bin/python`
- Running commands:
  - Inside `adgn/`, tools are on PATH (pytest, ruff, pre-commit, wt, rspcache, adgn-agent, ...)
  - From outside: prefix with `direnv exec adgn <command>`
- Refresh after edits:
  - `devenv.nix`/`.envrc` changes → `direnv reload`
  - `pyproject.toml` dependency changes → `direnv reload` (reinstalls dev extras on entry)

Note: The workspace `uv.lock` at `ducktape/` shares dependency resolution across packages. The per-package devenv still manages the local venv.

## Quick commands

- Run all tests (tests live under `adgn/tests`):
  - Inside `adgn/`.: `pytest tests`
  - From repo root: `direnv exec adgn pytest adgn/tests`
- Single test file/case: `direnv exec adgn pytest tests/util/test_unified_patch.py`
- **Debugging hangs/timeouts**: Run without xdist parallelization for clearer output: `pytest -n 0 -v --tb=long <test_path>`
- Lint/format: `ruff format .`, `ruff check . --fix`
- Pre-commit (preferred): `pre-commit install`, `pre-commit run -a`
- Optional extras (GNOME console script deps): `python -m pip install -e '.[gnome]'`

### Pytest Defaults

See `[tool.pytest.ini_options]` in `pyproject.toml` for current `addopts`, markers, and timeout settings.

- Hermetic git (pytest-env): `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`

## High-Level Module Map

- Packaging: name `adgn`, Python `>=3.13`
- Agent CLI (`adgn/agent/`) — simple stdin/stdout REPL
- MCP servers (`adgn/mcp/`) — Gitea mirror server
- Tools (`adgn/tools/`) — `trivial_patterns` linter, arg0 utilities
- Testing (`adgn/testing/`) — test fixtures, bootstrap helpers
- Utilities (`adgn/util/`) — shared utilities

**Moved to separate packages:**

- Response cache → `rspcache/`
- Properties/specimens → `props/`
- Instruction optimizer → `inop/`
- System rewriter → `sysrw/`
- Seatbelt → `mcp_infra/` (under `seatbelt/`)
- MCP compositor → `mcp_infra/`

## Console scripts

See `[project.scripts]` in `pyproject.toml` for the full list of CLI entry points.

- `adgn-agent` — Agent REPL
- `adgn-trivial-patterns` — Trivial patterns linter
- `adgn-mcp-gitea-mirror` — Gitea mirror MCP server

## Agent CLI

The `adgn-agent` command provides a simple stdin/stdout REPL for running agents:

```bash
adgn-agent run                               # Start REPL with default model
adgn-agent run --model gpt-4o               # Specify model
adgn-agent run --mcp-config extra.json      # Merge additional MCP config
```

- Model/system defaults: `--model` (OPENAI_MODEL, default `gpt-5.1-codex-mini`), `--system` (SYSTEM_INSTRUCTIONS)
- MCP configuration:
  - Baseline: if present, `./.mcp.json` in CWD is always loaded
  - Repeatable: `--mcp-config /path/extra.json` merges additional configs (later overrides earlier)
  - Embedded servers: prefer Streamable HTTP (`transport: "http"`) with bearer `auth` or `headers.Authorization`
  - Compatibility: `transport: "inproc"` with `factory` is still accepted, but runs over loopback HTTP

**Note:** The Agent UI/server functionality has moved to the `agent_server/` package. See `agent_server/README.md` for web-based agent management
