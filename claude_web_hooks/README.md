# Claude Web Hooks

Session hooks for Claude Code web environments.

## Session Start Hook

The hook runs at the start of each Claude Code web session and:

1. Installs Nix (with workaround for gVisor PTY bug)
2. Installs tools via `nix profile install`: direnv, devenv, uv
3. Allows `.envrc` files for the repository
4. Persists PATH to `CLAUDE_ENV_FILE`

See `.claude/settings.json` for hook configuration.

## Context

Claude Code web runs in ephemeral gVisor containers. Each session starts fresh, so any development tools (nix, direnv, devenv, uv) must be installed/configured by the hook before the agent can work effectively.

The repository uses:

- **devenv** (via nix) for reproducible dev environments
- **direnv** to automatically load `.envrc` when entering directories
- **uv** for Python package management
- A workspace-level `.envrc` that calls `use devenv`

## gVisor PTY Bug Workaround

The nix-env step fails in gVisor containers due to a PTY bug. When nix-env builds a derivation, it:

1. Opens /dev/ptmx to create a PTY pair (master fd)
2. Forks a child process for the build sandbox
3. Parent immediately calls read() on the PTY master
4. gVisor returns EIO instead of blocking until data arrives

The hook works around this by skipping nix-env and using the nix store path directly after the installer unpacks Nix to /nix/store.

## Important Constraint

**This package must not have any non-stdlib dependencies.**

It's used by session-start hooks which run before package installation.

## Testing

After session start, verify:

```bash
which direnv && direnv version
which devenv && devenv version
which uv && uv version
```

Check `/tmp/session-start-direnv.log` for hook execution details.
