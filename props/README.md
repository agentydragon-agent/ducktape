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

## Development Server Management (devenv + process-compose)

The backend, frontend, and PostgreSQL are managed by devenv via process-compose.

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

### Backend Watch Directories

The devenv backend watches:

- `backend/src` - Backend route handlers
- `core/src` - Props core package

Changes trigger automatic reload.

### Regenerating OpenAPI Schema

After backend API changes, rebuild the frontend (Bazel regenerates types automatically):

```bash
bazel build //props/frontend:bundle
```

## Database Management

### psql Access

```bash
cd props && direnv exec . psql # Uses PG* environment variables set by devenv
```

### Applying Migrations

For applying migrations to an existing database:

```bash
direnv exec . alembic upgrade head
```

## Specimens Dataset

**Specimens data lives in a separate repository**: <https://github.com/agentydragon/specimens>

The `ADGN_PROPS_SPECIMENS_ROOT` environment variable points to the specimens repo (typically `~/code/specimens`). The props package loads specimen data from this external location.
