@README.md

This file provides guidance to LLM agents for working with this repository.

@STYLE.md

## Before Hand-off

```bash
pre-commit run --all-files
```

If you touched `ansible/`, also follow the checklist in `ansible/AGENTS.md`.

## Repository Overview

"Ducktape" is a personal infrastructure repository — "duct tape" for personal infrastructure needs.

Manages configuration for: **agentydragon** (ThinkPad), **gpd** (GPD Win Max 2), **vps**, **atlas** (Proxmox/k3s).

## Directory Index

### Active Development

| Directory       | Purpose                          | Details                      |
| --------------- | -------------------------------- | ---------------------------- |
| `adgn/`         | LLM agent framework              | See `adgn/AGENTS.md`         |
| `agent_server/` | FastAPI backend, runtime, policy | See `agent_server/AGENTS.md` |
| `mcp_infra/`    | MCP compositor and utilities     | See `mcp_infra/AGENTS.md`    |
| `agent_pkg/`    | Agent package infrastructure     | See `agent_pkg/AGENTS.md`    |
| `tana/`         | Tana export toolkit              | See `tana/AGENTS.md`         |
| `wt/`           | Worktree management              | See `wt/AGENTS.md`           |
| `gatelet/`      | Gateway/tunneling                | See `gatelet/AGENTS.md`      |
| `ansible/`      | System configuration             | See `ansible/AGENTS.md`      |
| `docker/`       | Container images                 | See `docker/AGENTS.md`       |
| `dotfiles/`     | Shell configs, scripts           | See `dotfiles/AGENTS.md`     |
| `props/`        | Properties/specimens             | See `props/AGENTS.md`        |

### Less Active

| Directory          | Purpose                   |
| ------------------ | ------------------------- |
| `finance/`         | Portfolio tracking (Rust) |
| `trilium/`         | Trilium Notes extensions  |
| `inventree_utils/` | InventTree plugins        |
| `website/`         | Personal website (Hakyll) |
| `k8s/`             | k3s cluster configs       |

## Cross-Cutting Concerns

### Python / UV Workspace

Uses [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/):

- Single `uv.lock` at repo root
- Each package has `.envrc` + `devenv.nix` for per-package venv
- Run `direnv allow` in package directory to set up environment
- Target Python: 3.13+

```bash
# Per-package (recommended):
cd adgn && direnv allow

# Or workspace-level:
uv sync
```

### Other Build Systems

- **Rust** (`finance/`): `cargo build && cargo test`
- **Bazel**: `bazel build //target:name`

### Testing

- Test files: `test_*.py`
- Framework: pytest with pytest-asyncio
- Fixtures for shared setup

### Deployment

```bash
cd ansible
ansible-playbook <hostname>.yaml --ask-become-pass
```
