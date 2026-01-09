# Props Dashboard Backend

FastAPI backend for the props training/evaluation dashboard.

## Quick Start

```bash
# Start all services via devenv (from props/)
cd props && devenv up
```

The API will be available at `http://localhost:8000`.

## API Endpoints

- `GET /health` - Health check
- `GET /api/stats/overview` - Main dashboard data (definitions leaderboard)

## Project Structure

```
backend/
├── __init__.py          # Package root
├── app.py               # FastAPI app, lifespan
├── routes/
│   ├── runs.py          # Runs API + WebSocket
│   └── stats.py         # Stats API
├── TODO.md              # Implementation tasks
├── SPEC.md              # Feature specification
└── AGENTS.md            # Agent instructions
```

Frontend lives in `../frontend/`.

## Development

Requires the `props` package (workspace member) for database access.

```bash
# Start all services (from props/)
cd props && devenv up

# Regenerate API types after schema changes (requires backend running)
cd frontend && pnpm generate
```

## Key Dependencies

- **Backend:** FastAPI, SQLAlchemy, props.core.db, props.core.agent_registry
- **Frontend:** Svelte 5, Tailwind, openapi-fetch

## Props Integration

Backend imports from `props.core` package:

- `props.core.agent_registry.AgentRegistry` - Run critic/grader agents
- `props.core.db.models` - ORM models, views
- `props.core.db.config` - Database connection

Shared database is managed by props devenv (PostgreSQL container).
