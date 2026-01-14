# Props Ecosystem

High-level architecture and shared infrastructure for the props evaluation system.

## Directory Structure

```
props/
├── .envrc                    # Devenv entry point for env vars
├── devenv.nix                # Devenv config: sets PG* env vars for Docker Compose access
├── compose.yaml              # Docker Compose for postgres, registry, proxy
├── core/                     # Core Python library (props_core)
│   ├── pyproject.toml        # Package: props-core
│   ├── src/props_core/       # The Python package
│   └── tests/                # Tests for props_core
├── backend/                  # FastAPI dashboard backend
│   ├── pyproject.toml        # Package: props-backend
│   ├── src/props_backend/
│   └── tests/
└── frontend/                 # Svelte UI
    ├── package.json
    └── src/
```

## Initial Setup

```bash
cd props

# 1. Build and load proxy image (first time only)
bazelisk run //props/registry_proxy:load

# 2. Start infrastructure
docker compose up -d

# 3. Push built-in agent images to registry
bazelisk run //props/core/agent_defs/critic:push
bazelisk run //props/core/agent_defs/grader:push
bazelisk run //props/core/agent_defs/improvement:push
bazelisk run //props/core/agent_defs/prompt_optimizer:push
```

## Development

**Build system:** Bazel (see root AGENTS.md). The devenv.nix only sets environment variables for Docker Compose (PGHOST, PGPORT, etc.) - it does not manage Python packages.

```bash
docker compose up -d                       # Start infrastructure
docker compose down                        # Stop infrastructure
docker compose logs -f postgres            # View logs
bazelisk run //props/frontend:dev          # Frontend + backend with watch
bazelisk test //props/...                  # Run all tests
bazelisk build --config=check //props/...  # Lint + typecheck
```

### Service URLs

- Frontend: <http://localhost:5173>
- Backend: <http://localhost:8000>
- PostgreSQL: localhost:5433
- Registry: localhost:5050 (direct), localhost:5051 (proxy with ACL)

## Database Management

```bash
# psql access (uses PG* environment variables from devenv)
psql

# Recreate database from scratch (drops all data, runs migrations, syncs specimens)
bazelisk run //props/core:props -- db recreate

# Backup and restore
bazelisk run //props/core:props -- db backup
bazelisk run //props/core:props -- db restore <backup_file>
```

## Specimens Dataset

**Specimens data lives in a separate repository**: <https://github.com/agentydragon/specimens>

The `ADGN_PROPS_SPECIMENS_ROOT` environment variable points to the specimens repo (typically `~/code/specimens`).
The props package loads specimen data from this external location.
