# GitHub Copilot Instructions

This file provides instructions for GitHub Copilot and related AI coding assistants.

For detailed repository guidance, see: [AGENTS.md](../AGENTS.md)

## Repository Overview

"Ducktape" is a personal infrastructure repository containing various projects and utilities for managing configuration and deployment across multiple systems. Key areas:

- **LLM Tooling** (`llm/`, `adgn/`, `experimental/`) - Agent framework with MCP support
- **Infrastructure Automation** (`ansible/`) - System configuration and deployment
- **Development Tools** (`wt/`, `gatelet/`) - Worktree management and gateway services
- **Dotfiles** (`dotfiles/`) - Centrally managed via rcm (DO NOT modify files in `~/.` directly)

## Build Systems

### Python (UV Workspace)
The repository uses a UV workspace with a single `uv.lock` at the root:
```bash
# Install all workspace members
uv sync

# Or use per-package devenv
cd adgn && direnv allow
```
Target: Python 3.12+

### Rust
```bash
cargo build
cargo test
```

### Bazel
```bash
bazel build //target:name
bazel test //target:name
```

## Code Style

Follow conventions in [STYLE.md](../STYLE.md):
- **No exception swallowing**: Catch specific exceptions, let real errors surface
- **Prefer exceptions over error lists**: Raise exceptions on validation failure
- **Use Pydantic as typed objects**: Access fields directly (`model.field`), not `dict.get(...)`
- **Explicit keyword arguments**: Use `Model(field=value)`, not `**kwargs` unpacking
- **Use enum values directly**: `EnumClass.VALUE`, not string literals
- **Let exceptions propagate**: Define error boundaries once, don't catch/reformat at each call site

## Testing

- Test files: `test_*.py` in same directory as code
- Framework: pytest with pytest-asyncio
- Use fixtures for shared test components (prefer conftest.py)
- Keep test bodies concise and focused on assertions

## Pre-commit Hooks (Required)

**Before handing in any work, you MUST ensure pre-commit hooks pass.**

### Setup

Install pre-commit hooks when starting work:

```bash
pre-commit install
```

### Verification

Before completing your work, run the full pre-commit check:

```bash
pre-commit run --all-files
```

All checks must pass before the work is considered complete.

### Ansible-Specific Changes

If you modify any files in `ansible/`, follow the dedicated checklist in [`ansible/AGENTS.md`](../ansible/AGENTS.md).
