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
4. **Background installation**: Fire off `nix profile install` in background, don't wait for completion.
   LLM startup takes a few seconds anyway - install might complete by the time agent needs tools.

### Package Size Analysis

**Individual package sizes (download / unpacked):**

| Package | Download | Unpacked | Closure |
|---------|----------|----------|---------|
| direnv | 2.6 MB | 8.6 MB | 53.8 MB |
| uv | 14.6 MB | 59.5 MB | 105.9 MB |
| devenv | 6.0 MB | 21.9 MB | **277.0 MB** |

**Why is devenv so large?**

devenv bundles its own nix and cachix:
```
devenv-1.11.2 dependencies:
├── devenv-nix-2.30.4 (wrapper)
│   └── nix-2.30.4 (3.3 MB) ← duplicate of our nix 2.33.0!
├── cachix-1.9.1-bin (25 MB)
├── glibc, openssl, dbus, gcc-lib...
```

**Can devenv share our nix?** No. Tested 2025-12-29:
- devenv wrapper uses `--set DEVENV_NIX` (unconditional, can't override)
- Running unwrapped `.devenv-wrapped` with our nix fails:
  `unknown setting 'lazy-trees'` - devenv needs nix 2.30.4 features
- The two nix closures have **0 shared paths** (different versions = different hashes)

devenv's nix bundling is **required**, not a packaging mistake.

**The absurdity:** You need nix to install devenv, but devenv ignores that nix and uses its
own bundled fork. You're downloading nix to download a different nix. The fork lives at
[github.com/cachix/nix](https://github.com/cachix/nix) (branch `devenv-2.30.6`).

**Key insight: devenv.nix already provides uv**

Our `devenv.nix` has `languages.python.uv.enable = true`, so devenv provides uv directly.
We don't need to install uv separately. If we just had devenv, running `devenv shell` gives
us everything. direnv is only needed for auto-activation (which we can skip by running
`devenv shell` explicitly).

**Minimal bootstrap**: Get devenv → run `devenv shell` → done (uv, python, etc. provided)

**Alternatives investigated:**
- `apt-cache search devenv`: Not available in apt
- Standalone binary: No - devenv GitHub releases have no assets, distributed only via nix
- External nix support: No - devenv requires its bundled nix 2.30.4 fork (lazy-trees feature)
- [nix-portable](https://github.com/DavHau/nix-portable): 65 MB single static binary, no install needed.
  Could bootstrap devenv, but uses `~/.nix-portable/store` (won't benefit from persisted `/nix/store`)
- Minimal install (direnv + uv only): ~160 MB, might fit in timeout
- Skip devenv entirely: Loses reproducible environment, but Python work still possible

**Pre-installed in container:**
- `psql` 16.11 ✓ (no install needed)
- `docker` / `podman` ✗ (not available, and daemon likely not running anyway)

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

## Alternative: No-Nix Approach

Given the timeout issues with nix, consider abandoning devenv for Claude Code web and using
what's already in the container. This trades reproducibility for reliability.

### Container Pre-installed Tools (verified 2025-12-29)

| Tool | Version | Location |
|------|---------|----------|
| Python | 3.11.14 | /usr/local/bin/python3 |
| pip | 24.0 | /usr/bin/pip3 |
| Node.js | 22.21.1 | /opt/node22/bin/node |
| npm | (bundled) | /opt/node22/bin/npm |
| PostgreSQL | 16.11 | /usr/bin/psql, pg_ctlcluster |
| git | ✓ | /usr/bin/git |
| gcc/g++ | ✓ | /usr/bin/gcc |
| make | ✓ | /usr/bin/make |
| curl/wget | ✓ | /usr/bin |
| jq | ✓ | /usr/bin/jq |

**PostgreSQL cluster:** Pre-configured at port 5432, just needs `sudo pg_ctlcluster 16 main start`.

### What We'd Need to Install

| Tool | Method | Size | Time |
|------|--------|------|------|
| **uv** | Standalone binary from GitHub | 22 MB | ~7s |
| **direnv** | `apt install direnv` | ~2 MB | ~3s |

**Total: ~25 MB, ~10 seconds** vs nix approach (~370 MB, 2-3 minutes)

### Standalone uv Installation

```bash
curl -LsSf "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz" \
  | tar -xz -C ~/.local/bin --strip-components=1
```

Tested 2025-12-29: Works, produces `uv 0.9.18`.

### Proposed No-Nix Hook

```python
# Simplified hook - no nix, just uv + direnv
def setup_no_nix():
    # 1. Install uv standalone (22 MB, ~7s)
    if not shutil.which("uv"):
        subprocess.run([
            "curl", "-LsSf",
            "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz"
        ], stdout=subprocess.PIPE)
        # ... extract to ~/.local/bin

    # 2. Install direnv via apt (if not present)
    if not shutil.which("direnv"):
        subprocess.run(["sudo", "apt-get", "install", "-y", "direnv"])

    # 3. Start postgres if needed
    subprocess.run(["sudo", "pg_ctlcluster", "16", "main", "start"])

    # 4. Run uv sync for Python deps
    subprocess.run(["uv", "sync"])
```

### Trade-offs

**Pros:**
- Fast: ~10s vs 2-3 minutes
- Reliable: No timeout issues
- Simple: No nix complexity

**Cons:**
- Not reproducible: System Python 3.11 vs pinned Python 3.12
- No devenv services: Would need to manage postgres manually
- Diverges from local dev setup: Local uses devenv, web uses apt/standalone

### Hybrid Option

Keep nix approach for resumed sessions (which work), fall back to no-nix for fresh sessions:

```python
if nix_store_populated():
    use_nix_approach()  # Fast path, tools cached
else:
    use_no_nix_approach()  # Fresh session, can't wait for nix
```

## Non-Goals

- Getting a single session working manually
- Installing tools interactively during a conversation
- Workarounds that require agent cooperation
