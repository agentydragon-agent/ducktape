# Gatelet Development Instructions

## Development Container

**⚠️ IMPORTANT: ALL COMMANDS MUST BE RUN INSIDE THE DEVCONTAINER ⚠️**

This project uses a development container with PostgreSQL. If tests fail with "ModuleNotFoundError: No module named 'asyncpg'" or database connection errors, you are NOT in the devcontainer.

### Entering the Devcontainer

```bash
# Navigate to project root
cd /path/to/ducktape/ha-api/experimental/gatelet

# Start the devcontainer services
docker compose -f .devcontainer/docker-compose.yml up -d

# Enter the app container shell
docker compose -f .devcontainer/docker-compose.yml exec app bash
```

Once you're inside the container shell, you'll see a prompt like:
```
root@container_id:/workspace#
```

### Devcontainer Database Configuration

- Main database: `gatelet`
- Test database: `gatelet_test`
- Username: `postgres`
- Password: `postgres`
- Host: `db` (internal container network name)
- Port: `5432`

## Dependencies

Dependencies are defined in `pyproject.toml`:
- Main dependencies in `dependencies` section
- Development dependencies in `[project.optional-dependencies].dev` section

First-time setup inside the devcontainer:
```bash
# INSIDE DEVCONTAINER: Install project with dev dependencies
pip install -e '.[dev]'
```

## Testing Strategy

Tests are designed for execution INSIDE the devcontainer:
- Transaction-isolated to prevent cross-test contamination
- Each test uses a clean database state
- DB sessions are rolled back after each test

### Running Tests (INSIDE DEVCONTAINER)

```bash
# INSIDE DEVCONTAINER: Run all tests
python -m pytest

# INSIDE DEVCONTAINER: Run specific tests with verbosity
python -m pytest server/auth/ -v

# INSIDE DEVCONTAINER: Run a specific test file
python -m pytest server/auth/test_handlers.py

# INSIDE DEVCONTAINER: Run with coverage
python -m pytest --cov=server
```

## Development Commands (INSIDE DEVCONTAINER)

### Starting the Server

```bash
# INSIDE DEVCONTAINER: Start development server
uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

### Database Operations

```bash
# INSIDE DEVCONTAINER: Connect to database
psql -h db -U postgres -d gatelet

# INSIDE DEVCONTAINER: Connect to test database
psql -h db -U postgres -d gatelet_test

# INSIDE DEVCONTAINER: Run migrations
alembic upgrade head

# INSIDE DEVCONTAINER: Generate migration
alembic revision --autogenerate -m "Description of changes"
```

## Tools to Run Before Committing (INSIDE DEVCONTAINER)

```bash
# INSIDE DEVCONTAINER: Format code
black server/

# INSIDE DEVCONTAINER: Run linting
pylint server/

# INSIDE DEVCONTAINER: Run type checks
mypy server/

# INSIDE DEVCONTAINER: Run tests
python -m pytest
```