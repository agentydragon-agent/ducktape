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

### Python Code Conventions

- Follow PEP 8
- Use modern Python features when appropriate:
  - `match` statement
  - `:=` assignment operator
  - `X | Y` instead of `Union[X | Y]`
  - `X | None` instead of `Optional[X]`
  - `f"{var=}"` instead of `f"var={var}"`
  - `str.removeprefix`, `str.removesuffix` instead of slicing
  - `dict1 | dict2` (union), `dict1 & dict2` (intersection) for dicts and sets
  - `zoneinfo` builtin library
- Do not leave trailing whitespace in files
- Be aggressively DRY (Don't Repeat Yourself)
- Use early bail-out pattern
- Avoid broad try-catch blocks, catch specific exceptions only
- Use `typing.Self` or `from __future__ import annotations` for self-references
- Imports go at the top of files, not inside functions
- Use `pathlib` for path manipulation, not `os.path`
- Avoid `getattr`/`setattr` unless absolutely necessary

### Testing Conventions

- Test files should be placed in the same directory as the code they test
- Test files should be named `test_x.py` where `x.py` is the file being tested
- Use pytest for running tests
- Use the pytest-asyncio plugin for async tests (no need for explicit asyncio marks)
- Create shared pytest fixtures for reusable components, but avoid fixtures for single-use objects
- Use parameterized tests for similar test cases
- Keep tests concise by removing redundancy

### Ansible Development

For infrastructure configuration:

```bash
# Validate playbooks
ansible-playbook playbook.yaml --check

# Apply roles to specific hosts
ansible-playbook vps.yaml  # For VPS
ansible-playbook agentydragon.yaml  # For main laptop
ansible-playbook gpd.yaml  # For GPD laptop
```

## Deployment

The repository includes Ansible playbooks for deploying services to different hosts:

```bash
# Deploy to servers
cd ansible
ansible-playbook vps.yaml  # Deploy to VPS
ansible-playbook agentydragon.yaml  # Deploy to main laptop
ansible-playbook gpd.yaml  # Deploy to GPD laptop

# Deploy specific components
ansible-playbook vps.yaml --tags webhook_inbox
```

Dotfiles are managed and deployed through Ansible roles rather than direct rcm commands, ensuring consistent deployment across different hosts.
