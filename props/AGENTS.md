# Props Ecosystem

High-level architecture and shared infrastructure for the props evaluation system.

## Directory Structure

```
props/
├── .envrc                    # Single devenv entry point (shared by all)
├── devenv.nix                # Manages postgres, backend, frontend processes
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

## Component Documentation

- **Core library:** @core/src/props_core/AGENTS.md
- **Backend API:** @backend/AGENTS.md
- **Tests:** @core/tests/AGENTS.md

## Development Server Management (devenv + process-compose)

The backend, frontend, and PostgreSQL are managed by devenv via process-compose. **Never start these services manually.**

### Starting All Services

```bash
cd props
devenv up  # Starts postgres, backend, frontend
```

### Process Management Commands

```bash
# List processes and their status
process-compose process list

# Get detailed status of a process
process-compose process get backend

# View logs
process-compose process logs backend

# Restart a process (picks up code changes)
process-compose process restart backend

# Stop/start a process
process-compose process stop backend
process-compose process start backend
```

### Service URLs

- Backend: <http://localhost:8000>
- Frontend: <http://localhost:5173>
- PostgreSQL: localhost:5433

### What to NEVER Do

- **NEVER** run `uvicorn` manually
- **NEVER** run `pnpm dev` manually for the frontend
- **NEVER** start the postgres container manually
- **NEVER** kill service PIDs without checking if they're process-compose managed

Manual service starts will:

1. Block process-compose from starting (port conflict: "Address already in use")
2. Watch wrong directories (code changes won't reload)
3. Break the devenv-managed workflow

### Backend Watch Directories

The devenv backend watches:

- `backend/src` - Backend route handlers
- `core/src` - Props core package

Changes trigger automatic reload.

### Regenerating OpenAPI Schema

After backend API changes:

```bash
cd frontend
pnpm generate  # Requires backend running
```

## Database Management

### CRITICAL - NEVER DROP THE DATABASE WITHOUT PERMISSION

The `props db recreate` command drops ALL data including expensively-collected agent rollouts.

**NEVER run this command without the user's explicit verbal agreement.**

For applying migrations to an existing database, use the standard Alembic workflow:

```bash
cd core/src/props_core/db
direnv exec . alembic upgrade head
```

### psql Access

```bash
# Connect with psql (uses PG* environment variables set by devenv)
cd props && direnv exec . psql

# Or from anywhere:
cd /path/to/ducktape/props && direnv exec . psql
```

## Specimens Dataset

**Specimens data lives in a separate repository**: [github.com/agentydragon/specimens](https://github.com/agentydragon/specimens)

The `ADGN_PROPS_SPECIMENS_ROOT` environment variable points to the specimens repo (typically `~/code/specimens`). The props package loads specimen data from this external location.
