# Agent Isolation for Props

This document describes the isolation mechanisms available for running props agents in sandboxed environments.

## Overview

Props agents need to be isolated to prevent "cheating" - accessing reference solutions, modifying test cases, or using external resources that shouldn't be available during evaluation.

## Available Isolation Methods

### 1. Bubblewrap (Recommended)

**Status**: **Recommended for most use cases**

Strong isolation using Linux namespaces via bubblewrap:

```python
from props_core.bwrap_isolation import run_with_bwrap

result = run_with_bwrap(
    ["python3", "agent.py"],
    workspace_root=Path("/path/to/task"),
    readonly=False,
    timeout=60,
)
```

**Requirements**:
- bubblewrap package (`apt install bubblewrap`)
- User namespaces (widely available)

**Advantages**:
- ✓ True filesystem isolation (cannot escape sandbox)
- ✓ Process isolation (PID namespace)
- ✓ Works in nested containers and restricted environments
- ✓ No daemon required
- ✓ Minimal dependencies
- ✓ Read-only workspace enforcement actually works

**Limitations**:
- ✗ Network isolation unavailable (kernel limitations in nested containers)
- ✗ CPU/memory limits require additional setup

**Security Level**: **Good protection against cheating and casual attacks**

### 2. Docker/Podman (Production with Full Kernel)

**Status**: Strongest isolation when available

The codebase includes Docker-based isolation via `props/core/src/props_core/docker_env.py`:

```python
from props_core.docker_env import properties_docker_spec

wiring = properties_docker_spec(workspace_root, mount_properties=True)
```

**Requirements**:
- Docker or Podman installed
- OverlayFS kernel support
- iptables/nftables for networking
- Full cgroups access

**Limitations**:
- Does NOT work in nested containers
- Does NOT work in restricted sandbox environments
- Requires kernel features that may not be available

**Security Level**: **Strongest isolation available**

### 3. Simple Isolation (Last Resort Fallback)

**Status**: Works everywhere, but weakest isolation

A lightweight isolation mechanism using filesystem copying and permissions:

```python
from props_core.simple_isolation import isolated_workspace

task_files = {
    "main.py": "# agent code here",
    "data.json": '{"input": "value"}',
}
readonly_files = {
    "reference.txt": "Expected output",
}

with isolated_workspace(task_files, readonly_files) as ws:
    result = ws.run(["python3", "main.py"])
    output_files = ws.collect_files()
```

**How It Works**:
1. Creates a temporary directory
2. Copies task files (writable)
3. Copies reference files to `.readonly/` (read-only permissions)
4. Sets isolated HOME and TMPDIR
5. Runs command in isolated workspace
6. Collects modified files after execution

**What It Provides**:
- ✓ Isolated temporary workspace
- ✓ File modification tracking
- ✓ Read-only reference files
- ✓ Clean environment (HOME, TMPDIR)
- ✓ Output collection
- ✓ Works in any environment (no special kernel features needed)

**What It Does NOT Provide**:
- ✗ True filesystem isolation (agent can traverse to parent dirs)
- ✗ Network isolation
- ✗ CPU/memory limits
- ✗ Syscall filtering
- ✗ Protection against determined malicious code

**Security Level**: **Prevents accidental cheating only**

This is sufficient for:
- Development and testing
- Environments where neither Docker nor bubblewrap are available

This is NOT sufficient for:
- Any scenario where stronger isolation is available
- Untrusted/adversarial agents

## Choosing the Right Isolation Method

**Decision tree**:

1. **Is Docker/Podman available and working?**
   - Yes → Use Docker-based isolation (strongest)
   - No → Continue to 2

2. **Is bubblewrap available?**
   - Yes → Use bwrap_isolation (**recommended**)
   - No → Continue to 3

3. **Fall back to simple_isolation** (basic protection only)

### Auto-Detection Example

```python
import subprocess
import docker
from pathlib import Path


def get_best_isolation():
    """Automatically choose the best available isolation method."""
    # Try Docker first
    try:
        client = docker.from_env()
        client.ping()
        return "docker"
    except:
        pass

    # Try bubblewrap
    try:
        result = subprocess.run(
            ["bwrap", "--version"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return "bwrap"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fall back to simple
    return "simple"


# Use the best available method
method = get_best_isolation()

if method == "docker":
    from props_core.docker_env import properties_docker_spec
    wiring = properties_docker_spec(workspace_root)
elif method == "bwrap":
    from props_core.bwrap_isolation import run_with_bwrap
    result = run_with_bwrap(cmd, workspace_root=workspace)
else:
    from props_core.simple_isolation import run_in_isolation
    result, files = run_in_isolation(cmd, task_files)
```

## Usage Examples

### Bubblewrap Basic Usage

```python
from props_core.bwrap_isolation import BwrapIsolation
from pathlib import Path

# Create isolation instance
isolation = BwrapIsolation(
    workspace_root=Path("/path/to/task"),
    readonly_workspace=False,
)

# Run command
result = isolation.run(["python3", "agent.py"], timeout=60)
print(result.stdout)
```

### Simple Isolation Usage

```python
from props_core.simple_isolation import run_in_isolation

result, output_files = run_in_isolation(
    ["python3", "agent.py"],
    task_files={"agent.py": agent_code},
    readonly_files={"reference.txt": expected_output},
    timeout=30,
)

print(f"Exit code: {result.returncode}")
print(f"Output: {result.stdout}")
print(f"Created files: {list(output_files.keys())}")
```

## Testing

Run the test suites to verify isolation:

```bash
# Test bubblewrap isolation
python3 test_bwrap_simple.py

# Test simple isolation
python3 adgn/tests/props/test_simple_isolation.py

# Diagnose container support
bash adgn/docs/diagnose_container_support.sh
```

## Why Docker/Podman Don't Work in Some Environments

This environment (and many CI/sandbox environments) are missing:

1. **OverlayFS**: Container runtime's main filesystem driver
2. **iptables/nftables**: Network isolation and routing
3. **Full cgroups**: Resource limits
4. **Kernel interfaces**: `/proc/sys/kernel/*` tunables

This is typical when running inside:
- A container (nested containerization)
- CI/CD sandboxes
- Restricted cloud environments
- Kubernetes pods without privileged access

## Recommendations

| Use Case | Recommended Method | Why |
|----------|-------------------|-----|
| **Development** | bubblewrap | Fast, good isolation, works everywhere |
| **CI/Testing** | bubblewrap | Reliable, available in most CI systems |
| **Honest agents** | bubblewrap | Strong enough protection |
| **Untrusted agents** | Docker/Podman | Full containerization |
| **Bare metal/VM** | Docker/Podman | All features available |
| **Nested containers** | bubblewrap | Docker won't work |
| **No bubblewrap available** | simple_isolation | Last resort only |

### Quick Install

```bash
# Install bubblewrap (Ubuntu/Debian)
sudo apt install bubblewrap

# Or on RHEL/Fedora
sudo dnf install bubblewrap

# Verify it works
bwrap --version
```

## Isolation Comparison

| Feature | Docker/Podman | Bubblewrap | Simple |
|---------|--------------|------------|--------|
| Filesystem isolation | ✓✓✓ | ✓✓✓ | ✗ |
| Process isolation | ✓✓✓ | ✓✓ | ✗ |
| Network isolation | ✓✓✓ | ✗ | ✗ |
| Works in nested containers | ✗ | ✓ | ✓ |
| No daemon required | ✗ | ✓ | ✓ |
| Resource limits | ✓✓✓ | ✗ | ✗ |
| Works everywhere | ✗ | ✓✓ | ✓✓✓ |
| Security level | Excellent | Good | Minimal |

Legend: ✓✓✓ Excellent, ✓✓ Good, ✓ Basic, ✗ Not available
