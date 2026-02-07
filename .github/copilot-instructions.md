# GitHub Copilot Instructions

For detailed repository guidance, see: [AGENTS.md](../AGENTS.md) and [STYLE.md](../STYLE.md)

## Repository Overview

"Ducktape" is a personal infrastructure repository. Key areas:

- **Agent Framework** (`agent_cli/`, `agent_server/`, `agent_core/`, `agent_pkg/`) - Agent REPL, FastAPI backend, runtime
- **Props** (`props/`) - Code evaluation system with Docker-based E2E tests
- **MCP Infrastructure** (`mcp_infra/`) - MCP compositor and utilities
- **Infrastructure Automation** (`ansible/`) - System configuration and deployment
- **Development Tools** (`wt/`) - Worktree management
- **Dotfiles** (`dotfiles/`, `nix/home/`) - Shell configs (mostly Nix home-manager now)
- **Cluster** (`cluster/`) - k8s cluster configuration

## Build System

**Bazel** is the unified build system. Always use Bazel, never direct `pytest` or `python`:

```bash
bazel build //...                    # Build all
bazel test //...                     # Run all tests
bazel build --config=check //...     # Lint (ruff + mypy + eslint)
bazel run //tools/format             # Format code
bazel run //tools:gazelle            # Update BUILD files
```

Python 3.12+. Dependencies in `requirements_bazel.txt`.

## Verification (Required)

Before handing in any work:

```bash
bazel build --config=check //...   # Lint (ruff + mypy)
bazel test //...                   # Run all tests
```

For Rust code: `bazel build --config=rust-check //finance/...`

If you modified `ansible/`, follow the checklist in [ansible/AGENTS.md](../ansible/AGENTS.md).

## Testing

- Tests: `test_*.py` adjacent to the code they test
- Framework: pytest with pytest-asyncio (auto mode)
- All `py_test` targets MUST have `pytest_bazel.main()` entry point
- Do NOT add `@pytest.mark.asyncio` — auto mode handles it

## Props E2E Test Environment

The props ecosystem requires Docker infrastructure for E2E tests.

### Quick Setup

```bash
# Generate credentials
export PGPASSWORD=$(openssl rand -base64 24)
export OPENAI_API_KEY=test-key-not-used

# Build and pull images
bazel run //props/registry_proxy:load
bazel run //props/llm_proxy:load
docker pull postgres:16
docker pull registry:2

# Start infrastructure
cd props && docker compose up -d

# Wait for services
until pg_isready -h 127.0.0.1 -p 5433 -U postgres 2>/dev/null; do sleep 1; done
until curl -sf http://127.0.0.1:5050/v2/ 2>/dev/null; do sleep 1; done

# Initialize database
export PGHOST=127.0.0.1 PGPORT=5433 PGUSER=postgres PGDATABASE=eval_results
export ADGN_PROPS_SPECIMENS_ROOT="$PWD/props/testing/fixtures/testdata/specimens"
bazel run //props/cli:cli -- db recreate -y

# Push agent images
bazel run //props/critic:push
bazel run //props/grader:push
```

### Running Props E2E Tests

```bash
export PGHOST=127.0.0.1 PGPORT=5433 PGUSER=postgres PGDATABASE=eval_results
export AGENT_PGHOST=127.0.0.1
export PROPS_REGISTRY_PROXY_HOST=127.0.0.1 PROPS_REGISTRY_PROXY_PORT=5051
export PROPS_DOCKER_NETWORK=props-agents
export PROPS_E2E_HOST_HOSTNAME=172.17.0.1

bazel test --keep_going \
  //props/critic:test_e2e \
  //props/critic_dev/improve:test_e2e \
  //props/critic_dev/optimize:test_e2e \
  //props/core:test_agent_pkg_e2e
```

### Cleanup

```bash
cd props && docker compose down -v
```

### Environment Variables

Automatically configured in `copilot-setup-steps.yml`:

- `ADGN_PROPS_SPECIMENS_ROOT` — path to test specimen fixtures
- `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE` — PostgreSQL connection
- `AGENT_PGHOST` — PostgreSQL host for agent containers
- `PROPS_REGISTRY_PROXY_HOST`, `PROPS_REGISTRY_PROXY_PORT` — registry proxy
- `PROPS_DOCKER_NETWORK` — Docker network for agents (`props-agents`)
- `PROPS_E2E_HOST_HOSTNAME` — host address for containers (`172.17.0.1`)
