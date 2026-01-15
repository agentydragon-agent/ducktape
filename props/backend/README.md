# Props Dashboard Backend

FastAPI backend for the props training/evaluation dashboard.

## Quick Start

```bash
# Start infrastructure (from props/)
cd props && docker compose up -d

# Run frontend + backend dev servers with watch
bazelisk run //props/frontend:dev
```

The API will be available at `http://localhost:8000`.

## API Endpoints

- `GET /health` - Health check
- `GET /api/stats/overview` - Main dashboard data (definitions leaderboard)

## Project Structure

```
backend/
├── src/props_backend/
│   ├── app.py           # FastAPI app, lifespan
│   ├── routes/
│   │   ├── runs.py      # Runs API + WebSocket
│   │   └── stats.py     # Stats API
│   └── models.py        # Pydantic models
├── TODO.md              # Implementation tasks
├── SPEC.md              # Feature specification
└── AGENTS.md            # Agent instructions
```

Frontend lives in `../frontend/`.

## Development

Requires the `props` package (workspace member) for database access.

```bash
# Start infrastructure (from props/)
cd props && docker compose up -d

# Run frontend + backend dev servers
bazelisk run //props/frontend:dev

# Regenerate API types after schema changes
bazel build //props/frontend:bundle
```

## Key Dependencies

- **Backend:** FastAPI, SQLAlchemy, props_core.db, props_core.agent_registry
- **Frontend:** Svelte 5, Tailwind, openapi-fetch

## Props Integration

Backend imports from `props_core` package:

- `props_core.agent_registry.AgentRegistry` - Run critic/grader agents
- `props_core.db.models` - ORM models, views
- `props_core.db.config` - Database connection

Shared database is managed by Docker Compose (see `props/compose.yaml`).
