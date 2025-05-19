# Gatelet Development Instructions

You should have a `DATABASE_URL` env var set pointing to a usable database for tests.

## Dependencies

Dependencies are defined in `pyproject.toml`:
- Main dependencies in `dependencies` section
- Development dependencies in `[project.optional-dependencies].dev` section

First-time setup inside the devcontainer:
```bash
# Install project with dev dependencies
pip install -e '.[dev]'
```

## Testing Strategy

Tests are designed for execution INSIDE the devcontainer:
- Transaction-isolated to prevent cross-test contamination
- Each test uses a clean database state
- DB sessions are rolled back after each test

### Running Tests

```bash
# Run all tests
pytest
```

## Development Commands

### Starting the Server

```bash
# Start development server
uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

### Database Operations

```bash
# Connect to database
psql -h db -U postgres -d gatelet

# Connect to test database
psql -h db -U postgres -d gatelet_test

# Run migrations
alembic upgrade head

# Generate migration
alembic revision --autogenerate -m "Description of changes"
```

## Tools to Run Before Committing

Before committing, run `black`, `pylint`, `mypy`.
