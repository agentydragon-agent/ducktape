# Claude Code Web Docker Support

This document tracks the research and implementation of Docker/container support for running adgn tests in the Claude Code Web environment.

## Environment Analysis

### Container Type Detection

Claude Code Web runs in a **microVM** (likely Firecracker-based) on Google Compute Engine:

| Property | Value | Detection Method |
|----------|-------|-----------------|
| Root filesystem | 9p mount (virtio-fs style) | `mount \| grep 9p` |
| sys_vendor | "Google Compute Engine" | `/sys/class/dmi/id/sys_vendor` |
| Hypervisor | Yes | CPU flags include `hypervisor` |
| Seccomp | Disabled (`Seccomp: 0`) | `/proc/self/status` |
| Capabilities | Privileged (CAP_SYS_ADMIN, etc.) | `capsh --decode` |

### Environment Variables

Claude Code Web sets these identifying variables:

```bash
CLAUDE_CODE_REMOTE=true           # Primary indicator
CLAUDE_CODE_ENTRYPOINT=remote     # Confirms remote mode
IS_SANDBOX=yes                    # Sandbox/microVM mode
CLAUDE_CODE_SESSION_ID=...        # Session identifier
CLAUDE_CODE_CONTAINER_ID=...      # Container identifier
```

### /proc Filesystem Limitations

The microVM has an **incomplete /proc filesystem**, which prevents OCI runtimes from setting up network namespaces:

| Missing Path | Impact |
|--------------|--------|
| `/proc/self/setgroups` | crun runtime fails |
| `/proc/sys/net/ipv4/ping_group_range` | Network namespace setup fails |

## Container Runtime Options Evaluated

### Option 1: Podman with vfs + runc ✅ WORKS

```bash
apt-get install podman runc
# Configure vfs storage (overlay fails on 9p)
cat > /etc/containers/storage.conf << 'EOF'
[storage]
driver = "vfs"
EOF
# Start API service
podman --storage-driver=vfs --runtime=/usr/sbin/runc system service -t 0 unix:///run/podman/podman.sock &
# Create Docker-compatible symlink
ln -sf /run/podman/podman.sock /var/run/docker.sock
```

**Limitations:**
- Only `--network=host` works
- `--network=none` and `--network=bridge` fail with sysctl errors

### Option 2: Docker-in-Docker ❌ NOT TESTED

Would require Docker daemon installation and similar /proc limitations would apply.

### Option 3: crun runtime ❌ FAILS

crun fails with `/proc/self/setgroups` error before runc's network error.

### Option 4: QEMU nested VM ❌ TOO COMPLEX

Works but adds significant complexity and overhead.

## Hook Configuration

### Discovery Behavior

Claude Code Web looks for `.claude/settings.json` **only in the current working directory**, not parent directories.

**Sources:**
- [Issue #10367: Hooks Non-Functional in Subdirectories](https://github.com/anthropics/claude-code/issues/10367)
- [Issue #12962: Settings.json parent directory traversal for monorepos](https://github.com/anthropics/claude-code/issues/12962)

### Known Bugs

1. **Issue #10997**: SessionStart hooks fail on first run with GitHub marketplace plugins (async loading race condition)
2. **Issue #10373**: SessionStart hook output not injected into brand new conversations

### Implementation

Hook placed at repo root: `ducktape/.claude/settings.json`

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/session-start.sh"
      }]
    }]
  }
}
```

## Test Configuration

### Environment Detection Module

Created `adgn/src/adgn/testing/claude_code_web.py`:

```python
from adgn.testing.claude_code_web import is_claude_code_web, get_test_network_mode

# Returns True in Claude Code Web
is_claude_code_web()

# Returns "host" in Claude Code Web, "none" otherwise
get_test_network_mode("none")
```

### Pytest Markers

| Marker | Behavior |
|--------|----------|
| `@pytest.mark.requires_docker` | Skipped if Docker unavailable |
| `@pytest.mark.requires_network_isolation` | Skipped in Claude Code Web |

### conftest.py Changes

1. `make_container_opts()` now uses `get_test_network_mode()` by default
2. `pytest_runtest_setup()` skips `requires_network_isolation` tests when `supports_container_network_isolation=False`

## Test Results

### Working Tests

```
tests/mcp/exec/test_docker.py::test_hello_world PASSED
tests/mcp/exec/test_docker.py::test_stderr_and_exit_code PASSED
tests/mcp/exec/test_docker.py::test_timeout_flag PASSED
```

### Tests Requiring Network Isolation

Tests marked with `@pytest.mark.requires_network_isolation` should be used for:
- Critic agents that must not access external resources
- Tests validating network isolation behavior

These tests are automatically skipped in Claude Code Web.

## Files Changed

| File | Change |
|------|--------|
| `.claude/settings.json` | SessionStart hook config |
| `.claude/hooks/session-start.sh` | Setup script |
| `adgn/src/adgn/testing/__init__.py` | Module exports |
| `adgn/src/adgn/testing/claude_code_web.py` | Environment detection |
| `adgn/tests/conftest.py` | Network mode handling, new marker |
| `adgn/AGENTS.md` | Documentation with sources |
| `adgn/tests/mcp/sandboxed_jupyter/test_sandboxer_narrow.py` | Fixed marker |

## References

- [Claude Code Hooks Documentation](https://code.claude.com/docs/en/hooks)
- [Claude Code on the Web](https://code.claude.com/docs/en/claude-code-on-the-web.md)
- [GitHub Issue #10367: Hooks in Subdirectories](https://github.com/anthropics/claude-code/issues/10367)
- [GitHub Issue #12962: Monorepo Settings Traversal](https://github.com/anthropics/claude-code/issues/12962)
- [GitHub Issue #10997: First Run Hook Failure](https://github.com/anthropics/claude-code/issues/10997)
- [GitHub Issue #10373: SessionStart Output Injection](https://github.com/anthropics/claude-code/issues/10373)
