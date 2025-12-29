This file provides guidance to LLM agents for working with this repository.

@STYLE.md

## Before Hand-off

If you touch anything in `ansible/`, follow the dedicated checklist in `ansible/AGENTS.md` (manual yamllint + `ansible-playbook --syntax-check`, optional focused linting) first.  
After those targeted checks pass, finish with the full repo workflow:

```bash
pre-commit run --all-files
```

This final pass reruns yamllint + ansible-lint (and every other hook) so the hand-off state is fully verified.

## Repository Overview

"Ducktape" is a personal infrastructure repository containing various projects and utilities.
As the name suggests, it serves as "duct tape" for the owner's personal infrastructure needs.

This repository manages configuration and deployment for several systems:
- **agentydragon**: ThinkPad X1 Extreme 3rd Edition laptop (main development machine)
- **gpd**: GPD Win Max 2 laptop
- **vps**: Personal VPS server (hosts various services)
- **atlas**: Proxmox host (k3s cluster), hosting:
  - **new-vm**: Pop!_OS virtual machine

## Active Development Areas (High Churn)

1. **LLM Tooling** (`llm/`, `experimental/`, `adgn/`)
   - Agent framework with MCP support (`adgn/`)
   - Claude Code hooks and optimizer (`claude/claude_hooks/`, `claude/claude_optimizer/`)
   - LLM utilities and templates (`llm/ducktape_llm_common/`, `llm/claude-instructions/`)
   - Experimental LLM projects (`experimental/cotrl/`, `experimental/ember_evals/`)

2. **Development Tools** (`wt/`, `gatelet/`)
   - Worktree management system
   - Gateway/tunneling services
   - Remote development infrastructure

3. **Infrastructure Automation** (`ansible/`)
   - System configuration playbooks
   - Role development (GUI, CLI, dev environment)
   - Headscale VPN management

### Secondary Active Areas
- **Webhook Inbox** (`experimental/webhook_inbox/`)
- **Home Assistant Integration** (`homeassistant/iaqi/`)
- **Codex Configuration** (`dotfiles/codex/`)

## Dotfiles

Dotfiles are centrally managed via rcm with symlinks from home directory:

### Structure
- **Source**: `dotfiles/` directory in repository
- **Deployment**: Via rcm (managed by Ansible role `cli/tasks/dotfiles.yml`)
- **Configuration**: `dotfiles/rcrc` controls symlink behavior

### Key Symlinked Components
```
~/.bashrc -> ducktape/dotfiles/bashrc
~/.zshrc -> ducktape/dotfiles/zshrc
~/.config/* -> ducktape/dotfiles/config/*
~/.local/bin/* -> ducktape/dotfiles/local/bin/*
```

### User Scripts (.local/bin)
The repository provides numerous utility scripts symlinked to `~/.local/bin/`:
- Git AI commit tools (`git_commit_ai.py`, `git_prepare_commit_msg_ai.py`)
- Theme switchers (`set_dark_theme`, `set_light_theme`, `switch_gnome_terminal_profile`)
- Development utilities (`generate-agent-name`, `login_event_webhook_reporter.py`)
- Various helper scripts

### Important Notes
- **DO NOT modify dotfiles directly in ~/...  or in Ansible steps** - edit source files in `dotfiles/`
- Some dotfiles are host-specific (e.g., `host-agentydragon/rcrc`, `host-gpd/rcrc`)

### Shell configuration

Shell configuration follows a specific loading hierarchy:

@dotfiles/docs/shell-configuration.md

## Infrastructure Components

### Ansible Automation
The `ansible/` directory contains system configuration.
See: @ansible/README.md

#### Playbooks
- `agentydragon.yaml` - Main laptop configuration
- `vps.yaml` - VPS server deployment
- `gpd.yaml` - GPD laptop setup
- `wyrm.yaml` - Wyrm desktop provisioning

#### Key Roles
- **System Base**: `cli/`, `gui/`, `system/`, `user/`
- **Development**: `golang/`, `dev-env/`, `dev-clojure/`, `dev-ml/`
- **Services**: `webhook_inbox/`, `trilium_server/`, `headscale-server/`, `syncthing-server/`
- **Networking**: `tailscale-client/`

### Network Infrastructure
- **Headscale**: Self-hosted Tailscale controller (100.64.0.0/10)
- **Syncthing**: Cross-device file synchronization

## Less Active Components

These components exist but see minimal recent changes:

### Finance Tools (`finance/`)
- Worthy: Rust-based portfolio tracker (uses Cargo/Bazel)
- Reconciliation utilities for various financial systems

### Knowledge Management
- **Trilium Notes** (`trilium/`): Extensions and widgets
- **Tana Export** (`tana/`): Export utilities

### Other Tools
- **InventTree** (`inventree_utils/`): Inventory management plugins
- **Website** (`website/`): Personal website (Hakyll/Haskell)
- **Kubernetes** (`k8s/`): k3s cluster configurations

## Build Systems

### Python / UV Workspace

The repository uses a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) for Python packages:

```
ducktape/
├── pyproject.toml          # Workspace root (defines members)
├── uv.lock                  # Single lockfile for all packages
├── adgn/                    # Main LLM/agent package
├── tana/                    # Tana export utilities
└── agent_pkg/               # Agent package infrastructure
    ├── host/                # Host-side (image building, init runner)
    └── runtime/             # Container-side utilities (no adgn deps)
```

**Key points:**
- Single `uv.lock` at repo root with all resolved dependencies
- Run `uv sync` from `ducktape/` to install all workspace members
- Each package has its own `pyproject.toml` but shares the lockfile
- `agent_pkg/host` provides host-side image building and init runner
- `agent_pkg/runtime` is designed for Docker containers (minimal deps)

**Development workflow:**
- Each package (adgn, tana) has its own `.envrc` + `devenv.nix` that manages a local venv
- Run `direnv allow` in the package directory to set up the environment
- The workspace `uv.lock` ensures consistent dependency versions across packages
- devenv uses `uv sync` under the hood to install from the shared lockfile

```bash
# Per-package (recommended):
cd adgn && direnv allow      # Sets up venv at .devenv/state/venv

# Or workspace-level:
cd ducktape && uv sync       # Installs all members
```

- Target runtime version: Python 3.12+.

### Rust (Finance tools)
```bash
cargo build
cargo test
```

### Bazel (Various components)
```bash
bazel build //target:name
bazel test //target:name
```

## Development Practices

### Testing
- Test files: `test_*.py` in same directory as code
- Framework: pytest with pytest-asyncio
- Use fixtures for shared test components
- Keep tests concise and parameterized

### Deployment
```bash
cd ansible
ansible-playbook <hostname>.yaml --ask-become-pass
ansible-playbook vps.yaml --tags specific_service
```
