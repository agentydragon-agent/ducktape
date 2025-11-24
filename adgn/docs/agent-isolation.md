# Agent Isolation for Props

This document describes the isolation mechanisms available for running props agents in sandboxed environments.

## Overview

Props agents need to be isolated to prevent "cheating" - accessing reference solutions, modifying test cases, or using external resources that shouldn't be available during evaluation.

## Available Isolation Methods

### 1. Docker/Podman (Recommended for Production)

**Status**: Preferred when available

The codebase includes Docker-based isolation via `adgn/props/docker_env.py`:

```python
from adgn.props.docker_env import properties_docker_spec

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

### 2. Simple Isolation (Fallback)

**Status**: Working in all environments

A lightweight isolation mechanism using filesystem copying and permissions:

```python
from adgn.props.simple_isolation import isolated_workspace

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
- ✗ Network isolation (agent can still access network)
- ✗ CPU/memory limits
- ✗ Syscall filtering
- ✗ Protection against determined malicious code

**Security Level**: **Prevents accidental cheating, NOT malicious attacks**

This is sufficient for:
- Development and testing
- Honest agents that shouldn't access reference files
- Environments where Docker/Podman are unavailable

This is NOT sufficient for:
- Untrusted/adversarial agents
- Production security-critical evaluations
- Preventing determined attempts to break out

## Usage Examples

### Basic Usage

```python
from adgn.props.simple_isolation import run_in_isolation

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

### Context Manager

```python
from adgn.props.simple_isolation import isolated_workspace

with isolated_workspace(task_files) as ws:
    # Run multiple commands
    ws.run(["pip", "install", "-r", "requirements.txt"])
    result = ws.run(["python3", "main.py"])

    # Collect results
    files = ws.collect_files(pattern="*.json")
```

## Environment Detection

To automatically choose the best isolation method:

```python
import docker

def get_isolation_method():
    """Detect which isolation method to use."""
    try:
        client = docker.from_env()
        client.ping()
        return "docker"
    except:
        return "simple"

if get_isolation_method() == "docker":
    # Use Docker-based isolation
    from adgn.props.docker_env import properties_docker_spec
    wiring = properties_docker_spec(workspace_root)
else:
    # Use simple isolation
    from adgn.props.simple_isolation import isolated_workspace
    # ... use isolated_workspace ...
```

## Testing

Run the test suites to verify isolation:

```bash
# Test simple isolation
python3 test_simple_isolation.py

# Diagnose container support
./diagnose_container_support.sh
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

## Future Improvements

Possible enhancements to simple isolation:

1. **Network isolation**: Use `unshare --net` to disable networking
2. **Resource limits**: Use `ulimit` for basic CPU/memory caps
3. **Filesystem restrictions**: Use `unshare --mount` with proper pivotroot
4. **Process limits**: Use `prlimit` to prevent fork bombs

These would require:
- More complex setup with user namespaces
- Potentially root privileges
- May still fail in nested containers

## Recommendations

- **Development**: Use simple_isolation (always works)
- **CI/Testing**: Use simple_isolation (reliable)
- **Production with honest agents**: Use simple_isolation
- **Production with untrusted agents**: Use Docker/Podman on bare metal/VM
