# E2E Testing with Podman (Host Networking)

## Overview

Proposal for adapting the props system to run e2e tests in environments with:

- **Podman** instead of Docker
- **VFS storage driver** (no overlay filesystem)
- **Host networking only** (no network isolation)

This enables testing in gVisor sandboxes (Claude Code web environment) without full Docker network capabilities.

## Current Architecture vs Adapted Architecture

### Current (Docker with Network Isolation)

```
┌─────────────────────────────────────────────────────┐
│  props-internal network                             │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │  PostgreSQL  │  │  Registry    │  │   Proxy   │ │
│  │  :5432       │  │  :5000       │  │   :5051   │ │
│  └──────────────┘  └──────────────┘  └───────────┘ │
│                                          │          │
└──────────────────────────────────────────┼──────────┘
                                           │
┌──────────────────────────────────────────┼──────────┐
│  props-agents network                    │          │
│                     ┌────────────────────┘          │
│  ┌──────────────┐   │   ┌───────────┐              │
│  │  PostgreSQL  │───┴───│   Proxy   │              │
│  │              │       │           │              │
│  └──────────────┘       └───────────┘              │
│                                                     │
│  ┌───────────────────────────────────────────────┐ │
│  │  Agent Containers                             │ │
│  │  (cannot reach registry:5000 directly)        │ │
│  └───────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Adapted (Podman with Host Networking)

```
┌───────────────────────────────────────────────────────┐
│  Host Network (all services on 127.0.0.1)             │
│                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │  PostgreSQL  │  │  Registry    │  │   Proxy     │ │
│  │  127.0.0.1   │  │  127.0.0.1   │  │  127.0.0.1  │ │
│  │  :5433       │  │  :5050       │  │  :5051      │ │
│  └──────────────┘  └──────────────┘  └─────────────┘ │
│                                                        │
│  ┌──────────────────────────────────────────────────┐ │
│  │  Agent Containers (host network)                 │ │
│  │  - Can reach all services via 127.0.0.1          │ │
│  │  - Tests verify proxy logic, not enforcement     │ │
│  └──────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────┘
```

## Implementation Strategy

### 1. Infrastructure Services (podman containers)

All services run with `--network=host`:

```bash
# PostgreSQL
podman run --rm --network=host \
  --name props-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" \
  -e POSTGRES_DB=eval_results \
  -v props_eval_results_data:/var/lib/postgresql/data \
  postgres:16 \
  -c max_connections=200 \
  -p 5433

# OCI Registry
podman run --rm --network=host \
  --name props-registry \
  -e REGISTRY_HTTP_ADDR=:5050 \
  -v props_registry_data:/var/lib/registry \
  registry:2

# Registry Proxy
podman run --rm --network=host \
  --name props-registry-proxy \
  -e PROPS_REGISTRY_UPSTREAM_URL=http://127.0.0.1:5050 \
  -e PGHOST=127.0.0.1 -e PGPORT=5433 \
  -e PGUSER=postgres -e PGPASSWORD="$PG_PASSWORD" \
  -e PGDATABASE=eval_results \
  props-registry-proxy:latest
```

**Key changes:**

- All use `--network=host`
- Services bind to specific ports on 127.0.0.1
- Use localhost addresses instead of container names

### 2. Agent Containers

Agents also use host networking:

```python
# In agent_setup.py or equivalent
container = await docker_client.containers.create(
    config={
        "Image": image,
        "Env": [
            # Use localhost for all services
            "PGHOST=127.0.0.1",
            "PGPORT=5433",
            "PGUSER=agent_{run_id}",
            "PGPASSWORD={password}",
            "MCP_SERVER_URL=http://127.0.0.1:{mcp_port}",
            "MCP_SERVER_TOKEN={token}",
        ],
        "HostConfig": {
            "NetworkMode": "host",  # Instead of "props-agents"
            "StorageOpt": {
                "driver": "vfs"  # Required for gVisor
            }
        },
        "WorkingDir": "/workspace",
    }
)
```

**Registry access for agent-author agents:**

```python
# In agent container, agents use localhost
registry_url = "http://127.0.0.1:5051"  # Proxy port
auth = (username, password)
```

### 3. Code Changes Required

#### a. Docker Client Abstraction

Add podman socket support:

```python
# props/core/docker_client.py (new file)
import os
from pathlib import Path
import aiodocker

def get_docker_client() -> aiodocker.Docker:
    """Get Docker/Podman client based on environment."""
    # Check for podman socket
    podman_socket = Path("/run/user") / str(os.getuid()) / "podman/podman.sock"
    if podman_socket.exists():
        return aiodocker.Docker(url=f"unix://{podman_socket}")

    # Check for Docker socket
    docker_socket = Path("/var/run/docker.sock")
    if docker_socket.exists():
        return aiodocker.Docker(url=f"unix://{docker_socket}")

    raise RuntimeError("Neither Docker nor Podman socket found")
```

#### b. Network Configuration

Create config that adapts based on environment:

```python
# props/core/config.py additions
from dataclasses import dataclass

@dataclass
class RuntimeConfig:
    """Runtime environment configuration."""

    # Network mode
    use_network_isolation: bool = True  # False for host networking

    # Service addresses
    postgres_host: str = "props-postgres"  # Or "127.0.0.1"
    postgres_port: int = 5432  # Or 5433
    registry_host: str = "props-registry"  # Or "127.0.0.1"
    registry_port: int = 5000  # Or 5050
    proxy_host: str = "registry-proxy"  # Or "127.0.0.1"
    proxy_port: int = 5050  # Or 5051

    @classmethod
    def from_environment(cls) -> "RuntimeConfig":
        """Detect runtime environment and return appropriate config."""
        # Detect podman vs Docker
        use_podman = Path("/run/user").exists() and not Path("/var/run/docker.sock").exists()

        if use_podman or os.getenv("PROPS_USE_HOST_NETWORK"):
            return cls(
                use_network_isolation=False,
                postgres_host="127.0.0.1",
                postgres_port=5433,
                registry_host="127.0.0.1",
                registry_port=5050,
                proxy_host="127.0.0.1",
                proxy_port=5051,
            )
        else:
            # Docker with network isolation (current setup)
            return cls(
                use_network_isolation=True,
                postgres_host="props-postgres",
                postgres_port=5432,
                registry_host="props-registry",
                registry_port=5000,
                proxy_host="registry-proxy",
                proxy_port=5050,
            )
```

#### c. AgentEnvironment Updates

Update container creation to use runtime config:

```python
# props/core/agent_setup.py
from props.core.config import RuntimeConfig

class AgentEnvironment(ABC):
    def __init__(
        self,
        runtime_config: RuntimeConfig = RuntimeConfig.from_environment(),
        ...
    ):
        self._runtime_config = runtime_config
        ...

    async def _create_container(self, ...):
        config = {
            "Image": self._image,
            "Env": [
                f"PGHOST={self._runtime_config.postgres_host}",
                f"PGPORT={self._runtime_config.postgres_port}",
                ...
            ],
            "HostConfig": {
                "NetworkMode": "host" if not self._runtime_config.use_network_isolation else self._network,
            }
        }

        # Add VFS driver if using host networking (likely podman)
        if not self._runtime_config.use_network_isolation:
            config["HostConfig"]["StorageOpt"] = {"driver": "vfs"}

        return await self._docker_client.containers.create(config=config)
```

### 4. Test Configuration

Update pytest fixtures to support both modes:

```python
# props/core/tests/conftest.py additions

@pytest.fixture
def runtime_config():
    """Provide runtime config for tests."""
    return RuntimeConfig.from_environment()

@pytest_asyncio.fixture
async def test_registry(synced_test_db, async_docker_client, test_workspace_manager, runtime_config):
    """Provide AgentRegistry for tests, handling cleanup."""
    registry = AgentRegistry(
        docker_client=async_docker_client,
        db_config=synced_test_db,
        workspace_manager=test_workspace_manager,
        runtime_config=runtime_config,  # Pass config
    )
    yield registry
    await registry.close()
```

### 5. Process-Compose Configuration for Podman

Create alternative devenv config for podman environments:

```bash
# props/devenv-podman.sh (startup script for podman environment)
#!/bin/bash
set -euo pipefail

# Generate password
mkdir -p .devenv/state
if [ ! -f .devenv/state/pg_password ]; then
    openssl rand -base64 32 > .devenv/state/pg_password
fi
PG_PASSWORD=$(cat .devenv/state/pg_password)

# Start PostgreSQL
podman run --rm -d --network=host \
  --name props-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" \
  -e POSTGRES_DB=eval_results \
  -v props_eval_results_data:/var/lib/postgresql/data \
  postgres:16 \
  postgres -c max_connections=200 -p 5433

# Wait for postgres
until PGPASSWORD="$PG_PASSWORD" psql -h 127.0.0.1 -p 5433 -U postgres -d postgres -c '\q' 2>/dev/null; do
  echo "Waiting for postgres..."
  sleep 1
done

# Start Registry
podman run --rm -d --network=host \
  --name props-registry \
  -e REGISTRY_HTTP_ADDR=:5050 \
  -v props_registry_data:/var/lib/registry \
  registry:2

# Wait for registry
until curl -sf http://127.0.0.1:5050/v2/ >/dev/null 2>&1; do
  echo "Waiting for registry..."
  sleep 1
done

# Build proxy image if needed
if ! podman image inspect props-registry-proxy:latest >/dev/null 2>&1; then
  echo "Building proxy image..."
  bazelisk run //props/registry_proxy:load
fi

# Start Proxy
podman run --rm -d --network=host \
  --name props-registry-proxy \
  -e PROPS_REGISTRY_UPSTREAM_URL=http://127.0.0.1:5050 \
  -e PGHOST=127.0.0.1 -e PGPORT=5433 \
  -e PGUSER=postgres -e PGPASSWORD="$PG_PASSWORD" \
  -e PGDATABASE=eval_results \
  props-registry-proxy:latest

# Wait for proxy
until curl -sf http://127.0.0.1:5051/v2/ >/dev/null 2>&1; do
  echo "Waiting for proxy..."
  sleep 1
done

echo "Infrastructure ready!"
echo "PostgreSQL: 127.0.0.1:5433"
echo "Registry: 127.0.0.1:5050"
echo "Proxy: 127.0.0.1:5051"
echo ""
echo "Environment variables:"
echo "export PGHOST=127.0.0.1"
echo "export PGPORT=5433"
echo "export PGUSER=postgres"
echo "export PGPASSWORD='$PG_PASSWORD'"
echo "export PGDATABASE=eval_results"
echo "export PROPS_USE_HOST_NETWORK=1"
```

### 6. Running Tests

```bash
# Start infrastructure (podman version)
./props/devenv-podman.sh &

# Set environment
export PROPS_USE_HOST_NETWORK=1
export PGHOST=127.0.0.1
export PGPORT=5433
export PGUSER=postgres
export PGPASSWORD=$(cat .devenv/state/pg_password)
export PGDATABASE=eval_results

# Run database migrations
cd props
alembic upgrade head

# Run e2e tests
pytest core/tests/critic/test_e2e.py -m requires_docker
```

## Trade-offs

### What We Lose

1. **Network isolation enforcement**: Agents can technically reach registry:5050 directly
2. **Port conflicts**: All services must use unique ports on host
3. **Service discovery**: Must use localhost addresses instead of container names

### What We Keep

1. **Functional correctness**: Tests verify proxy ACL logic works
2. **Agent capabilities**: All agent workflows function correctly
3. **Database isolation**: RLS policies still enforce data scoping
4. **End-to-end validation**: Full stack testing from agent launch to results

### What We Gain

1. **Podman compatibility**: Works in rootless podman environments
2. **gVisor compatibility**: VFS storage + host networking work in sandboxes
3. **Simplified networking**: No need to manage Docker networks
4. **Faster iteration**: Easier to debug (all services on localhost)

## Security Considerations

**For E2E testing (acceptable):**

- Network isolation not enforced, but proxy ACL logic is tested
- Tests verify the proxy correctly validates credentials and enforces permissions
- Tests verify agents can/cannot perform operations based on their type

**For production (not acceptable):**

- Network isolation is a critical security boundary
- Production deployments should use Docker with network isolation
- This podman setup is **development/testing only**

## Migration Path

1. **Phase 1**: Add runtime config abstraction (no behavior change)
2. **Phase 2**: Test with Docker + host networking (verify compatibility)
3. **Phase 3**: Test with podman + host networking (Claude Code web env)
4. **Phase 4**: Update CI to test both modes

## Testing Strategy

Tests verify **functional correctness**, not **security enforcement**:

```python
# Example: Test proxy ACL allows/denies correctly
async def test_proxy_acl_allows_agent_author_push():
    """Verify proxy allows agent authors to push by digest."""
    # Agent author credentials
    response = httpx.put(
        f"http://127.0.0.1:5051/v2/critic/manifests/{digest}",
        auth=(agent_username, agent_password),
        content=manifest_json
    )
    assert response.status_code == 201  # Allowed

async def test_proxy_acl_denies_critic_push():
    """Verify proxy denies critic agents push access."""
    # Critic credentials
    response = httpx.put(
        f"http://127.0.0.1:5051/v2/critic/manifests/{digest}",
        auth=(critic_username, critic_password),
        content=manifest_json
    )
    assert response.status_code == 403  # Forbidden
```

Tests don't verify that critics **cannot bypass** the proxy (network isolation), just that the proxy **correctly enforces** ACL when used.

## Summary

This proposal enables e2e testing in podman + host networking environments by:

1. Using localhost addresses for all services
2. Detecting runtime environment and adapting configuration
3. Accepting that network isolation isn't enforced (tests verify ACL logic only)
4. Keeping production Docker setup unchanged

**Result**: Full e2e test coverage in Claude Code web environment without requiring overlay filesystem or Docker network isolation.
