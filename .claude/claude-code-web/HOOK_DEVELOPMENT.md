# Session Start Hook Development

## Goal

Create a **reproducible, self-contained session-start hook** that automatically sets up the development environment for Claude Code web sessions. The hook must work reliably every time a new session starts - manual intervention is not acceptable.

## Context

Claude Code web runs in ephemeral gVisor containers. Each session starts fresh, so any development tools (nix, direnv, devenv) must be installed/configured by the hook before the agent can work effectively.

The repository uses:
- **Bazel** as the unified build system (via Aspect CLI for linting)
- **devenv** (via nix) for reproducible dev environments
- **direnv** to automatically load `.envrc` when entering directories
- A workspace-level `.envrc` that calls `use devenv`

## Current State (2025-12-29)

The hook (`session-start-direnv.py`) attempts to:
1. Install nix (with workaround for gVisor PTY bug)
2. Install direnv, devenv, uv via `nix profile install`
3. Allow `.envrc` files
4. Persist PATH to `CLAUDE_ENV_FILE`

### What Works
- Nix installation succeeds (manual profile linking bypasses gVisor PTY bug)
- Network access works fine - `nix profile install` CAN download packages successfully
- `CLAUDE_ENV_FILE` mechanism for persisting environment

### What Fails
- The hook hangs after installing direnv, appearing to fail at devenv installation
- Log shows: "Installing direnv..." then "Installing devenv..." with no completion

### Root Cause: Profile Self-Destruction (CONFIRMED 2025-12-29)

**The bug is NOT network-related.** The actual issue is in the hook's profile setup:

1. The hook's gVisor workaround creates a manual symlink:
   ```
   ~/.nix-profile -> /nix/var/nix/profiles/per-user/root/profile -> /nix/store/...-nix-2.33.0
   ```

2. When `nix profile install nixpkgs#direnv` runs, nix creates a NEW profile:
   ```
   profile -> profile-1-link -> /nix/store/...-new-profile (contains direnv, NOT nix)
   ```

3. The nix binary is no longer in `~/.nix-profile/bin/` - the profile now only contains direnv

4. The next `nix profile install nixpkgs#devenv` fails because `nix` command is not found

**Proof:** After manually running `nix profile install nixpkgs#hello`:
```
$ ls ~/.nix-profile/bin/
hello    # nix is GONE
```

But nix is still in the store:
```
$ /nix/store/yg8v8aap26967f28xmqgvl29ksp6mgn1-nix-2.33.0/bin/nix --version
nix (Nix) 2.33.0
```

### The Fix (IMPLEMENTED 2025-12-29)

The hook now uses the nix store path directly, NOT the profile path:

1. `install_nix()` returns the store bin path
2. `install_tools()` uses that path to run nix commands
3. `persist_environment()` adds BOTH paths to PATH:
   - Nix store bin (for running nix commands)
   - Profile bin (for user-installed tools)

Key changes:
- Removed manual profile symlinking (no longer needed)
- Install all tools in one `nix profile install` command
- Use `nix_store_bin / "nix"` instead of `which("nix")`

## Requirements for a Working Solution

1. **No manual intervention** - The hook must complete successfully without human help
2. **Idempotent** - Safe to run multiple times
3. **Fast** - Session startup should not take minutes
4. **Resilient** - Must handle network issues gracefully (timeout, fallback)

## Testing the Hook

To verify the hook works, check:
```bash
# These should all succeed after session start:
which direnv && direnv version
which devenv && devenv version
which bazel && bazel version

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

## Bazel Proxy Setup (Added 2025-12-30)

Claude Code web uses a TLS-inspecting proxy that breaks Bazel's access to the
Bazel Central Registry (BCR). The hook now automatically sets up a workaround:

### The Problem

1. Claude Code proxy does TLS inspection with a custom CA
2. Proxy uses JWT-based authentication in proxy credentials
3. Bazel's Java-based BCR client uses JVM properties, not env vars
4. Java's Authenticator only responds to HTTP 407, but proxy returns 401

### The Solution

The hook automatically:

1. **Extracts the TLS inspection CA** from the proxy via openssl
2. **Creates a Java truststore** with the CA
3. **Starts a local proxy wrapper** at `127.0.0.1:18081` that adds auth headers
4. **Writes ~/.bazelrc** with JVM properties for proxy and truststore

### Verification

After session start, check:
```bash
# Proxy should be running
curl -s --max-time 5 -x http://127.0.0.1:18081 https://bcr.bazel.build/ | head -1

# Bazel should be able to access BCR
bazel info

# Check proxy log
cat ~/.cache/bazel-proxy/proxy.log
```

### Files

All proxy-related files are stored in `~/.cache/bazel-proxy/`:

- `anthropic_ca.pem` - Extracted TLS inspection CA
- `cacerts.jks` - Java truststore with CA
- `bazelrc` - Proxy startup options (try-imported from ~/.bazelrc)
- `proxy.log` - Proxy output log

Checked into repo:
- `.claude/claude-code-web/bazel_proxy.py` - Async proxy server

## Non-Goals

- Getting a single session working manually
- Installing tools interactively during a conversation
- Workarounds that require agent cooperation
