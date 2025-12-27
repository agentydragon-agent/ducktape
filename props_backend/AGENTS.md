# Props Backend Agent Guide

## Documentation Convention

This project uses two companion files for tracking work:

### TODO.md

**Purpose:** Captures implementation tasks to work on later.

- Edited as things are completed (check off items)
- Organized by priority (High/Medium/Lower)
- Tracks current component and endpoint status
- Living document - update frequently

### SPEC.md

**Purpose:** Evolving specification of the "target desired state" to reconcile to.

- Append-only (don't delete features, only add)
- Describes what features should exist when complete
- Reference for conformance checking
- Includes CLI features to migrate, live display requirements, future extensions

**Workflow:** When implementing, check TODO.md for what to do next and SPEC.md for what the end result should look like.

## Project Structure

```
props_backend/
├── src/props_backend/
│   ├── app.py           # FastAPI app, lifespan
│   ├── routes/
│   │   ├── runs.py      # Runs API + WebSocket
│   │   └── stats.py     # Stats API
│   └── models.py        # Pydantic models
├── TODO.md              # Implementation tasks
├── SPEC.md              # Feature specification
└── AGENTS.md            # This file
```

Frontend lives in `../props_frontend/`.

## Development

```bash
# Start backend (from props_backend/)
direnv exec . uvicorn props_backend.app:app --reload --port 8000

# Start frontend (from props_frontend/)
pnpm dev

# Regenerate API types after schema changes
cd props_frontend && pnpm generate
```

## Key Dependencies

- **Backend:** FastAPI, SQLAlchemy, props.db, props.agent_registry
- **Frontend:** Svelte 5, Tailwind, openapi-fetch

## Props Integration

Backend imports from `props` package:
- `props.agent_registry.AgentRegistry` - Run critic/grader agents
- `props.db.models` - ORM models, views
- `props.db.config` - Database connection

Shared database is managed by props devenv (PostgreSQL container).
