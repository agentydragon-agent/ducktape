# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

"Ducktape" is a personal infrastructure repository containing various projects and utilities. As the name suggests, it serves as "duct tape" for the owner's personal infrastructure needs. The repository contains multiple independent components across different domains.

This repository manages configuration and applications for three systems:
- **agentydragon**: ThinkPad X1 Extreme 3rd Edition laptop
- **gpd**: GPD Win Max 2 laptop
- **vps**: Personal VPS server

## Repository Components

1. **Finance Tools**
   - Worthy: A Rust-based financial portfolio tracking tool (uses Cargo/Bazel)
   - Reconciliation utilities for various financial systems (Python)

2. **Home Automation**
   - Home Assistant custom components (Python)
   - HA API integration for LLMs (current development task)
   - Webhook inbox system (Python/FastAPI)

3. **Personal Knowledge Management**
   - Trilium Notes extensions and widgets (JavaScript)
   - LogSeq configurations and templates
   - Tana export utilities (Python)

4. **Infrastructure Automation**
   - Ansible playbooks and roles for system configuration
   - Dotfiles management for multiple machines (deployed via Ansible)
   - Custom system services

5. **InventTree Integration**
   - Custom plugins and utilities for InventTree (Python)
   - Label templates and tooling

## Build Systems and Dependencies

The repository uses different build systems for different components:

### Python Components
Most Python projects use standard Python tooling:

```bash
# Use pip/venv for most Python components
pip install -r requirements.txt
python -m pytest

# Only certain Python components use Bazel:
bazel run //:requirements.update  # Update Python requirements lock
```

### Rust Components (Finance/Worthy)
The finance tools use Cargo and Bazel with cargo-raze:

```bash
# Direct Cargo use
cargo build
cargo test

# Or via Bazel
bazel build //finance/worthy:target
```

### Website
The personal website uses Hakyll (Haskell):

```bash
# Built using Bazel's Haskell rules
bazel build //website:site
```

## Code Organization

Directories follow a domain-based organization:

- `ansible/`: Ansible roles and playbooks for system configuration
- `dotfiles/`: Configuration files for all systems (agentydragon, gpd, vps)
- `experimental/`: Experimental projects and utilities
- `finance/`: Financial tools and utilities
- `homeassistant/`: Home Assistant custom components
- `inventree_utils/`: InventTree plugins and utilities
- `llm/`: LLM-related tools and configurations
- `trilium/`: Trilium Notes extensions and scripts
- `website/`: Personal website source code

## Development Practices

### Python Development

When working on Python code in this repository:

```bash
# Use pre-commit hooks
pip install pre-commit
pre-commit install
```

### Testing Conventions

- Test files should be placed in the same directory as the code they test
- Test files should be named `test_x.py` where `x.py` is the file being tested
- Use pytest for running tests

### Ansible Development

For infrastructure configuration:

```bash
# Validate playbooks
ansible-playbook -i inventory.yaml playbook.yaml --check

# Apply roles to specific hosts
ansible-playbook -i inventory.yaml vps.yaml  # For VPS
ansible-playbook -i inventory.yaml agentydragon.yaml  # For main laptop
ansible-playbook -i inventory.yaml gpd.yaml  # For GPD laptop
```

## Deployment

The repository includes Ansible playbooks for deploying services to different hosts:

```bash
# Deploy to servers
cd ansible
ansible-playbook -i inventory.yaml vps.yaml  # Deploy to VPS
ansible-playbook -i inventory.yaml agentydragon.yaml  # Deploy to main laptop
ansible-playbook -i inventory.yaml gpd.yaml  # Deploy to GPD laptop

# Deploy specific components
ansible-playbook -i inventory.yaml vps.yaml --tags webhook_inbox
```

Dotfiles are managed and deployed through Ansible roles rather than direct rcm commands, ensuring consistent deployment across different hosts.