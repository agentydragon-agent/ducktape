# adgn

Local tools and libraries for my dev/worktree/LLM workflows.

- LLM utilities: Agent REPL, properties/specimens, system rewriter, etc.
- MCP servers and compositors
- Docker-based agent execution

## Workspace

`adgn` is part of a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/):

```
ducktape/
├── pyproject.toml          # Workspace root
├── uv.lock                  # Shared lockfile
├── adgn/                    # This package
├── tana/                    # Tana export utilities
└── agent_pkg/               # Agent package infrastructure
    ├── host/                # Host-side (image building, init runner)
    └── runtime/             # Container-side utilities
```

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
- Single test file/case: `direnv exec tana pytest tests/tana/test_convert.py::test_node_export`
- **Debugging hangs/timeouts**: Run without xdist parallelization for clearer output: `pytest -n 0 -v --tb=long <test_path>`
- Lint/format: `ruff format .`, `ruff check . --fix`
- Pre-commit (preferred): `pre-commit install`, `pre-commit run -a`
- Optional extras (GNOME console script deps): `python -m pip install -e '.[gnome]'`

### Pytest Defaults

See `[tool.pytest.ini_options]` in `pyproject.toml` for current `addopts`, markers, and timeout settings.

- Hermetic git (pytest-env): `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`

## High-Level Module Map

- Packaging: name `adgn`, Python `>=3.13`, src layout under `src/`
- Response cache (`src/adgn/rspcache/`)
  - `responses_db.py`; CLI `rspcache`
- LLM toolkit and agent (`src/adgn/llm/*`, `src/adgn/agent/*`, `src/adgn/mcp/*`, `src/adgn/props/*`)
  - Agent REPL, MCP utilities, instruction optimizer, properties/specimens
- Seatbelt (`src/adgn/seatbelt/`) — sandbox policy validation and compilation
- Instruction optimizer (`src/adgn/inop/`) — Claude instruction optimization
- Tools (`src/adgn/tools/`) — `trivial_patterns` linter, arg0 utilities

## Console scripts

See `[project.scripts]` in `pyproject.toml` for the full list of CLI entry points.

- rspcache → adgn.rspcache.cli:main
- LLM: adgn-agent, adgn-llm-edit, adgn-sysrw, props, sandbox-jupyter
- Worktree tooling (`wt`, `wt-install`) now lives in the sibling `wt/` project

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

## More details

- See ./CLAUDE.md for a deeper guide (conventions, LLM toolkit patterns).

## Runtime container image (container mode)

- Build the base image used for both runtime exec and policy evaluation (run from workspace root `ducktape/`):
  - `docker build -t adgn-runtime:latest -f docker/runtime/Dockerfile .`
  - Set `ADGN_RUNTIME_IMAGE=adgn-runtime:latest` to use this image everywhere.
