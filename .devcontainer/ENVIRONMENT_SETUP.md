# GitHub Copilot Agents Environment Setup

## Overview

This document describes the environment setup for GitHub Copilot Agents (and other coding agents that may use devcontainer.json), including available options, decisions made, and rationale.

## Environment Comparison

### Claude Code Web (gVisor Sandbox)

**Environment characteristics:**
- **Container**: gVisor-based sandbox with restricted syscalls
- **Filesystem**: 9p filesystem (doesn't support hard links on Unix sockets)
- **Networking**: All network access goes through TLS-inspecting proxy with custom CA certificate
- **Proxy**: Anthropic's TLS-inspecting proxy requiring JWT authentication
- **Docker/Podman**: Not pre-installed; podman configured via session hook
- **Bazel**: Not pre-installed; installed via session hook
- **Services**: Managed via supervisord (using TCP socket due to 9p limitations)

**Setup requirements:**
- Extract and configure custom CA certificate for TLS inspection
- Set up local proxy (port 18081) to add authentication headers
- Create Java truststore with custom CA for Bazel
- Configure all network tools (curl, node, python) to trust custom CA
- Install bazelisk and create wrapper script
- Configure podman for gVisor compatibility (vfs storage driver)
- Use supervisord for process management (no systemd available)

### GitHub Copilot / GitHub Codespaces / Standard CI

**Environment characteristics:**
- **Container**: Standard Linux container (or bare metal CI runner)
- **Filesystem**: Standard overlay or ext4 filesystem
- **Networking**: Direct internet access, standard DNS resolution
- **Proxy**: No proxy (or optional corporate proxy with standard configuration)
- **Docker/Podman**: Pre-installed and working
- **Bazel**: Pre-installed (bazel + bazelisk available)
- **Services**: Can use systemd, docker, or simple background processes

**Setup requirements:**
- Minimal - most tools already available
- No proxy setup needed
- No custom CA configuration needed
- No container runtime setup needed
- May want to install git hooks, nix, and development tools
- May want to configure direnv for environment management

## Design Decisions

### 1. Reuse Session Start Hook Logic

**Decision**: Extend `tools/claude_hooks/session_start.py` to support a new "standard" mode for GitHub Copilot and similar environments.

**Rationale**:
- Avoids code duplication
- Centralizes environment setup logic
- Makes it easy to add features to all environments
- Follows DRY principle

**Implementation**:
- Add environment variable `CLAUDE_HOOKS_MODE` to control behavior
- Modes: `web` (Claude Code web), `cli` (direnv), `standard` (GitHub Copilot)
- Skip proxy setup when not needed (via `CLAUDE_HOOKS_SKIP_PROXY` env var)
- Skip bazelisk installation when already available (via `CLAUDE_HOOKS_SKIP_BAZELISK` env var)

### 2. Skip Proxy Setup

**Decision**: Do not set up the Bazel proxy in GitHub Copilot environments.

**Rationale**:
- GitHub Copilot has direct internet access
- No TLS-inspecting proxy to work around
- System CA bundle is sufficient
- Reduces complexity and startup time
- Fewer moving parts = fewer failure points

**Configuration**: Set `CLAUDE_HOOKS_SKIP_PROXY=1` in devcontainer.json

### 3. Use Pre-installed Services

**Decision**: Use pre-installed Docker/Podman instead of setting up via session hook.

**Rationale**:
- Docker 28.0.4 and Podman 4.9.3 are already installed
- No need for supervisord to manage podman service
- Standard configuration works out of the box
- Simpler and faster startup

**Verification**:
```bash
$ docker version
Docker version 28.0.4, build b8034c0

$ podman version
Podman version 4.9.3
```

### 4. Use Pre-installed Bazel

**Decision**: Use pre-installed bazel/bazelisk instead of installing via session hook.

**Rationale**:
- Bazelisk is already available at `/usr/local/bin/bazelisk`
- Bazel is already available at `/usr/local/bin/bazel`
- No need to download and install
- Faster startup time

**Configuration**: Set `CLAUDE_HOOKS_SKIP_BAZELISK=1` in devcontainer.json

**Verification**:
```bash
$ which bazel bazelisk
/usr/local/bin/bazel
/usr/local/bin/bazelisk
```

### 5. Skip Supervisor Setup

**Decision**: Do not start supervisord in GitHub Copilot environments.

**Rationale**:
- Supervisor was needed in Claude Code web for:
  - Managing bazel proxy process (not needed without proxy)
  - Managing podman service (not needed with pre-installed docker/podman)
- GitHub Copilot has systemd or can use simple background processes
- Reduces complexity

**Configuration**: Skip supervisor setup when proxy is skipped

### 6. Standard Networking

**Decision**: Use standard networking (not host networking).

**Rationale**:
- GitHub Copilot/Codespaces containers have standard network stack
- No special networking configuration needed
- Host networking would require additional permissions
- Standard networking is more portable and secure

### 7. Keep Essential Setup Steps

**Decision**: Still run these setup steps from session_start.py:

1. **Git hooks**: Install pre-commit hooks for code quality
2. **Development tools**: Install cluster tools (opentofu, tflint) if missing
3. **Nix**: Install Nix for nix-based tooling (optional, may fail gracefully)

**Rationale**:
- These are useful regardless of environment
- They don't require proxy or special networking
- Installation can fail gracefully if not needed

## Configuration Summary

### Environment Variables for GitHub Copilot Mode

Set in `.devcontainer/devcontainer.json`:

```json
{
  "containerEnv": {
    "CLAUDE_HOOKS_MODE": "standard",
    "CLAUDE_HOOKS_SKIP_PROXY": "1",
    "CLAUDE_HOOKS_SKIP_BAZELISK": "1",
    "CLAUDE_HOOKS_SKIP_PODMAN": "1"
  }
}
```

### What Gets Set Up

- ✅ Git pre-commit hooks (via pre-commit framework)
- ✅ Development tools (opentofu, tflint, etc.)
- ✅ Nix installation (optional, may be skipped if too slow)
- ❌ Bazel proxy (not needed)
- ❌ Custom CA configuration (not needed)
- ❌ Bazelisk installation (already available)
- ❌ Podman setup (already available)
- ❌ Supervisord (not needed)

## Testing

To test the setup:

```bash
# 1. Check git hooks installed
ls -la .git/hooks/pre-commit

# 2. Verify bazel works
bazel version

# 3. Check docker/podman available
docker version
podman version

# 4. Run bazel build to test full setup
bazel build //...

# 5. Run bazel tests
bazel test //...
```

## References

- **Claude Code Web Documentation**: [tools/claude_hooks/README.md](../tools/claude_hooks/README.md)
- **Session Start Hook**: [tools/claude_hooks/session_start.py](../tools/claude_hooks/session_start.py)
- **Devcontainer Specification**: https://containers.dev/
- **GitHub Codespaces**: https://docs.github.com/en/codespaces
- **GitHub Copilot**: https://docs.github.com/en/copilot

## Future Improvements

1. Consider using devcontainer features for standard tool installation
2. Add support for other CI environments (GitLab, Bitbucket, etc.)
3. Create a unified configuration file for all environment modes
4. Add telemetry to track which features are actually used in each environment
