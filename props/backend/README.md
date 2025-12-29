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

## Development

Requires the `props` package (workspace member) for database access.
