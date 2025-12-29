# Session Start Hook Development

## Goal

Create a **reproducible, self-contained session-start hook** that automatically sets up the development environment for Claude Code web sessions. The hook must work reliably every time a new session starts - manual intervention is not acceptable.

## Context

Claude Code web runs in ephemeral gVisor containers. Each session starts fresh, so any development tools (nix, direnv, devenv, uv) must be installed/configured by the hook before the agent can work effectively.

The repository uses:
- **devenv** (via nix) for reproducible dev environments
- **direnv** to automatically load `.envrc` when entering directories
- **uv** for Python package management
- A workspace-level `.envrc` that calls `use devenv`

## Current State (2025-12-29)

The hook (`session-start-direnv.py`) attempts to:
1. Install nix (with workaround for gVisor PTY bug)
2. Install direnv, devenv, uv via `nix profile install`
3. Allow `.envrc` files
4. Persist PATH to `CLAUDE_ENV_FILE`

### What Works
- Nix installation succeeds (manual profile linking bypasses gVisor PTY bug)
- `CLAUDE_ENV_FILE` mechanism for persisting environment

### What Fails
- `nix profile install nixpkgs#<tool>` fails with "Truncated tar archive" errors
- This is a network/proxy issue when fetching nixpkgs from GitHub
- The hook hangs indefinitely waiting for package installation

## Requirements for a Working Solution

1. **No manual intervention** - The hook must complete successfully without human help
2. **Idempotent** - Safe to run multiple times
3. **Fast** - Session startup should not take minutes
4. **Resilient** - Must handle network issues gracefully (timeout, fallback)

## Potential Approaches

### Option A: apt fallback for tools
Install direnv/uv via apt when nix fails. devenv is nix-only, so this requires either:
- A simplified `.envrc` that doesn't use devenv
- A separate Claude Code web `.envrc` that just runs `uv sync`

### Option B: Pre-built closure
Ship a nix closure with required tools already built. Avoids network fetches during session startup.

### Option C: Direct binary downloads
Download pre-built binaries for direnv, devenv, uv from GitHub releases. Bypasses nix entirely for tool installation.

### Option D: Timeout + degraded mode
Add timeouts to nix commands. If they fail, log a warning and continue with whatever tools are available (the container has Python, uv may be pre-installed).

## Testing the Hook

To verify the hook works, check:
```bash
# These should all succeed after session start:
which direnv && direnv version
which devenv && devenv version
which uv && uv version

# Environment should be loaded:
echo $DIRENV_DIR  # Should be set if .envrc loaded
```

Check `/tmp/session-start-direnv.log` for hook execution details.

## Files Involved

- `.claude/hooks/session-start.json` - Hook configuration
- `.claude/session-start-direnv.py` - Main hook script
- `.claude/claude-code-web/nix.conf` - Nix configuration for web environment
- `.envrc` - Repository-level direnv config (uses devenv)
- `devenv.nix` - devenv configuration

## Non-Goals

- Getting a single session working manually
- Installing tools interactively during a conversation
- Workarounds that require agent cooperation
