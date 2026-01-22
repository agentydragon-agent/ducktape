# GitHub Copilot Coding Agent Configuration

## Overview

This document explains how GitHub Copilot coding agent works with this repository and what configuration is available.

## What is GitHub Copilot Coding Agent?

GitHub Copilot coding agent is an AI agent that you can assign issues to on GitHub.com. When assigned, it:
- Analyzes the issue and repository context
- Creates a plan and implements changes
- Opens a pull request with the changes
- Responds to feedback and comments

**Important**: Unlike Claude Code session hooks, GitHub Copilot coding agent runs on GitHub's managed infrastructure, not in your local environment. Therefore, it does NOT support custom environment setup hooks or scripts.

## How GitHub Copilot Coding Agent Works

1. **Runs on GitHub Infrastructure**: The agent executes in GitHub's managed environment
2. **Uses Repository Context**: It reads your code, issues, PRs, and configuration files  
3. **Follows Custom Instructions**: It reads `.github/copilot-instructions.md` for repo-specific guidance
4. **No Environment Setup Needed**: GitHub provides the runtime environment

## Available Configuration

### 1. Repository Custom Instructions (`.github/COPILOT_INSTRUCTIONS.md`)

**What it is**: Instructions file that tells Copilot how to work with your repository.

**Location**: `.github/COPILOT_INSTRUCTIONS.md` (this repository already has this file)

**What to include**:
- Repository overview and structure
- Build and test commands
- Code style guidelines  
- Common pitfalls and workarounds
- Verification steps

**Example from this repository**:
```markdown
## Build System

bazel build //...   # Build all targets
bazel test //...    # Run all tests
bazel lint //...    # Lint (ruff + mypy)
```

### 2. Agent Instructions (`AGENTS.md` files)

**What it is**: Per-directory instructions for AI agents.

**Location**: Can be anywhere in the repository. The nearest `AGENTS.md` in the directory tree takes precedence.

**This repository has**: `AGENTS.md` in the root directory

### 3. Path-Specific Instructions

**What it is**: Instructions that apply to specific file paths.

**Location**: `.github/instructions/NAME.instructions.md`

**Not currently used in this repository**.

## Comparison with Claude Code Hooks

| Feature | Claude Code Hooks | GitHub Copilot Coding Agent |
|---------|------------------|----------------------------|
| **Execution Environment** | User's local machine or gVisor sandbox | GitHub's managed infrastructure |
| **Environment Setup** | Custom via `session_start.py` | Managed by GitHub (no custom setup) |
| **Proxy Configuration** | Supported (required for Claude Web) | Not needed (GitHub handles networking) |
| **Custom Tool Installation** | Supported (bazelisk, nix, etc.) | Not supported (uses GitHub's tooling) |
| **Configuration Method** | Python hooks + shell scripts | Markdown instructions files |
| **Working Directory** | User's repository clone | Temporary GitHub workspace |

## What GitHub Copilot Coding Agent Has Access To

✅ **Available**:
- All repository code and files
- Git history
- Issues and PRs
- GitHub Actions workflows
- Custom instructions from `.github/copilot-instructions.md`
- Standard development tools (node, python, go, etc.)
- GitHub's build infrastructure

❌ **Not Available**:
- Custom environment setup scripts
- Local proxy configuration  
- Custom CA certificates
- Supervisor/process management
- Local service configuration (podman, docker daemon, etc.)

## Best Practices for This Repository

### 1. Keep COPILOT_INSTRUCTIONS.md Updated

When you make significant changes to:
- Build system (Bazel configurations)
- Test infrastructure
- Development workflows
- Repository structure

Update `.github/COPILOT_INSTRUCTIONS.md` to reflect these changes.

### 2. Document Common Issues

Add common pitfalls and workarounds to the instructions:
```markdown
## Known Issues

- **Issue**: Bazel tests fail with "No such file or directory"
- **Solution**: Run `bazel clean` first, then `bazel test //...`
```

### 3. Provide Clear Build Instructions

Always include the exact commands to run:
```markdown
# Correct (specific)
bazel build //...

# Avoid (vague)
"Build the project"
```

### 4. Use AGENTS.md for Directory-Specific Context

For complex subdirectories (like `ansible/`), create local `AGENTS.md` files with context specific to that area.

## When to Use GitHub Codespaces Instead

If you need custom environment setup (like what Claude Code hooks provide), use **GitHub Codespaces** with `.devcontainer/devcontainer.json`:

- Custom Docker images
- Environment variables
- Tool installations via lifecycle hooks  
- Service configuration

**Note**: Codespaces is for interactive development, not for the GitHub Copilot coding agent which runs automatically in the background.

## References

- [GitHub Copilot Documentation](https://docs.github.com/en/copilot)
- [Adding Custom Instructions](https://docs.github.com/en/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot)
- [GitHub Copilot Coding Agent](https://github.com/features/copilot/agents)
- [Existing COPILOT_INSTRUCTIONS.md](../COPILOT_INSTRUCTIONS.md)
- [Existing AGENTS.md](../../AGENTS.md)

## Summary

**For GitHub Copilot coding agent**: Use `.github/COPILOT_INSTRUCTIONS.md` and `AGENTS.md` files. No environment setup hooks are supported.

**For custom environment setup**: Use GitHub Codespaces with `.devcontainer/` configuration, or Claude Code session hooks for Claude environments.
