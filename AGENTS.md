This file provides guidance to LLM agents for working with this repository.

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

1. **LLM Tooling** (`llm/`, `experimental/`)
   - Claude Code hooks and integration (`claude_hooks/`, `claude/`)
   - AI teams and spawn systems (`llm/ai-teams/`)
   - MCP (Model Context Protocol) tools (`llm/mcp/`)
   - Claude linter and optimizer tools

2. **Development Tools** (`wt/`, `gatelet/`)
   - Worktree management system
   - Gateway/tunneling services
   - Remote development infrastructure

3. **Infrastructure Automation** (`ansible/`)
   - System configuration playbooks
   - Role development (GUI, CLI, dev environment)
   - WireGuard/Headscale VPN management

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
- `new-vm.yaml` - VM provisioning

#### Key Roles
- **System Base**: `cli/`, `gui/`, `system/`, `user/`
- **Development**: `golang/`, `dev-env/`, `dev-clojure/`, `dev-ml/`
- **Services**: `webhook_inbox/`, `trilium_server/`, `headscale-server/`, `syncthing-server/`
- **Networking**: `wireguard/`, `tailscale-client/`

### Network Infrastructure
- **WireGuard VPN**: Hub-and-spoke topology with VPS as hub (10.13.13.0/24)
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

### Python (Most Common)
```bash
pip install -r requirements.txt
python -m pytest
pre-commit install  # For development
```
- Target runtime version: Python 3.12 (stdlib features like `tomllib` are assumed available).
- Each active project directory has a `.envrc`; run `direnv allow` so the expected Python/UV environments and PATH customisations load automatically before running tooling.

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
