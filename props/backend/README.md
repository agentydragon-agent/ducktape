# Props Dashboard Backend

FastAPI backend for the props training/evaluation dashboard.

## Quick Start

```bash
# Start development server
props-backend serve --reload

# Or with uvicorn directly
uvicorn props_backend.app:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

## API Endpoints

- `GET /health` - Health check
- `GET /api/stats/overview` - Main dashboard data (definitions leaderboard)

## Development

Requires the `props` package (workspace member) for database access.
