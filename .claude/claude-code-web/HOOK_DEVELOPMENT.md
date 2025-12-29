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
- Nix installation succeeds
- Network access works - `nix profile install` downloads packages successfully
- `CLAUDE_ENV_FILE` mechanism for persisting environment
- Using nix store path directly (avoids profile self-destruction bug)
- Resumed sessions work perfectly (nix store persists)

### Known Issues

#### 1. Hook Timeout on Fresh Sessions

**Symptom:** Hook log shows "Installing tools: direnv, devenv, uv" then stops abruptly.

**Root Cause:** `nix profile install` takes 2-3 minutes on a fresh session (downloading ~70 MiB
for devenv + dependencies), but Claude Code hooks have a short timeout (~30-60s).

**Evidence from testing (2025-12-29):**

Fresh session (hook killed by timeout):
```
[session-start-direnv] Installing tools: direnv, devenv
# ... log ends abruptly, no completion message
```

Agent running same command after hook timeout:
- `nix profile install nixpkgs#hello` with 30s timeout: killed by timeout
- Same command with 180s timeout: completes in ~13s (from cached store)
- `nix profile install nixpkgs#devenv nixpkgs#uv`: ~2-3 minutes cold

Resumed session (nix store persisted, 2611 entries):
```
[session-start-direnv] cache.nixos.org: HTTP/1.1 200 OK (0.24s)
[session-start-direnv] /nix/store entries: 2611
[session-start-direnv] All tools already available: direnv, devenv, uv
[session-start-direnv] Setup complete (total: 7.5s)
```

**Bandwidth testing:**
- cache.nixos.org: ~3 MB/s sustained
- Flake metadata lookup: ~1s
- 84 MB total (devenv + direnv + uv + deps) = ~28s download time
- BUT: first `nix profile install` on cold flake registry takes much longer (flake evaluation)

**Key insight:** Hook and agent share the same network environment (same proxy settings,
same connectivity to cache.nixos.org). The difference is purely timeout - the hook gets
killed before nix can finish downloading.

**Workarounds under investigation:**
1. Increase hook timeout (if configurable)
2. Pre-warm nix store with commonly needed packages
3. Use smaller/faster tool alternatives

#### 2. Profile Self-Destruction (FIXED 2025-12-29)

**Previously:** `nix profile install` would replace the profile, removing nix from PATH.

**Fix:** Hook now uses nix store path directly (`/nix/store/...-nix-X.Y.Z/bin/nix`)
instead of relying on `~/.nix-profile/bin/nix`.

### Diagnostics

The hook now logs:
- Network connectivity check (curl to cache.nixos.org with timing)
- Proxy settings (truncated)
- /nix/store entry count (helps identify fresh vs resumed sessions)
- Timing for each step (nix install, tool install)
- Total elapsed time

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
