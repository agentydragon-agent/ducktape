# adgn

Local tools and libraries for my dev/worktree/LLM workflows.

- LLM utilities: Agent client/UI, properties/specimens, system rewriter, etc.
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
├── agent_pkg/               # Host-side agent package infrastructure
└── agent_pkg_runtime/       # Thin container utilities
```

## Environment and setup (direnv + devenv)
- Requirements: Nix + devenv, direnv; Python 3.12+
- First time here: `direnv allow`
  - This loads .envrc → devenv, creates a Python venv at `.devenv/state/venv`, and installs the package in editable mode with dev extras.
- With devenv active, dev tools are on PATH automatically (pytest, ruff, pre-commit, wt, rspcache, …). Run them directly without prefixes when inside adgn/.
- Running from outside this dir (or scripts): prefix commands with `direnv exec adgn …`

Note: The workspace `uv.lock` at `ducktape/` shares dependency resolution across packages. The per-package devenv still manages the local venv.

## Quick commands
- Run all tests (tests live under `adgn/tests`):
  - Inside `adgn/`.: `pytest tests`
  - From repo root: `direnv exec adgn pytest adgn/tests`
- Single test file/case: `direnv exec tana pytest tests/tana/test_convert.py::test_node_export`
- Lint/format: `ruff format .`, `ruff check . --fix`
- Pre-commit: `pre-commit install`, `pre-commit run -a`

## Agent Presets (Agent UI)
- Agents are created from presets (YAML) discovered via platformdirs:
  - `platformdirs.user_config_dir('adgn')/presets`
  - Examples: Linux `~/.config/adgn/presets`, macOS `~/Library/Application Support/adgn/presets`
  - Override via `ADGN_AGENT_PRESETS_DIR=/path/to/presets`
- Generic example preset (no organization-specific details) is provided here:
  - `examples/presets/generic-sandbox.yaml`
  - Copy it into your presets directory (above) or set `ADGN_AGENT_PRESETS_DIR` to the `examples/presets` folder to try it.
- See the in-repo example for a concrete template you can copy and adapt: `examples/presets/generic-sandbox.yaml`.

- API endpoints:
  - `GET /api/presets` → list available presets
  - `POST /api/agents {"preset":"dev-echo"}` → create a new agent from a preset
  - UI: Agents sidebar offers a Preset dropdown + Create button
  - System prompt in the preset is combined with an MCP servers header at agent start

## Console scripts
- rspcache → adgn.rspcache.cli:main
- LLM: adgn-agent, adgn-llm-edit, adgn-sysrw, props, sandbox-jupyter
- Worktree tooling (`wt`, `wt-install`) now lives in the sibling `wt/` project

## More details
- See ./CLAUDE.md for a deeper guide (test config, module map, LLM toolkit notes).

## Runtime container image (container mode)
- Build the base image used for both runtime exec and policy evaluation (run from workspace root `ducktape/`):
  - `docker build -t adgn-runtime:latest -f docker/runtime/Dockerfile .`
  - Set `ADGN_RUNTIME_IMAGE=adgn-runtime:latest` to use this image everywhere.
