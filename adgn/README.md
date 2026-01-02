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
└── agent_pkg/               # Agent package infrastructure
    ├── host/                # Host-side (image building, init runner)
    └── runtime/             # Container-side utilities
```

## Development

See [AGENTS.md](../AGENTS.md) for standard Bazel workflow (`bazel lint //...`, `bazel test //...`).

Run CLI: `bazel run //adgn:adgn-agent`

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
