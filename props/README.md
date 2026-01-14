# Props Ecosystem

High-level architecture and shared infrastructure for the props evaluation system.

## Directory Structure

```
props/
├── .envrc                    # Single devenv entry point (shared by all)
├── devenv.nix                # Manages postgres, registry, proxy processes
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

# 1. Start infrastructure (postgres, registry, proxy)
# Devenv manages PostgreSQL, registry, and proxy via process-compose.
devenv up

# 2. In another terminal, push built-in agent images to registry
bazelisk run //props/core/agent_defs/critic:push
bazelisk run //props/core/agent_defs/grader:push
bazelisk run //props/core/agent_defs/improvement:push
bazelisk run //props/core/agent_defs/prompt_optimizer:push
bazelisk run //props/registry_proxy:push
```

## Development

Process management:

```bash
process-compose process list              # List processes
process-compose process logs postgres     # View logs
process-compose process restart registry  # Restart a process
```

### Frontend + Backend

```bash
bazelisk run //props/frontend:dev  # Starts both frontend and backend with watch
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
