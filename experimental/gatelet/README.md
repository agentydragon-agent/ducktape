# Gatelet

Service that lets LLMs access real-time and historical information relevant to the user, providing a browsable interface focused on Home Assistant integration.

### Core Components

1. **Server** - FastAPI-based web service that:
   - Receives and stores webhooks in PostgreSQL
   - Provides browsable interface optimized for LLMs
   - Retrieves and presents Home Assistant data 
   - Offers multiple authentication methods
   - Includes admin interface for humans

2. **Reporter** - Python scripts that:
   - Send event data to the server
   - Can be installed on laptops and other devices

## Development Setup

The project requires Python 3.10+ and a PostgreSQL database. A quick reproducible setup uses Docker for the database.

1. Start PostgreSQL in Docker:

```bash
docker run --name gatelet-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=gatelet -p 5432:5432 -d postgres:16
```

2. Create a virtual environment and install Gatelet with development dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

3. Copy the example configuration and set the database URL:

```bash
cp gatelet.example.toml gatelet.toml
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gatelet
```

4. Initialize the database and start the server:

```bash
alembic upgrade head
uvicorn server.app:app --reload --host 0.0.0.0 --port 8000
```

The service will be available at http://localhost:8000. When finished, stop the database container with:

```bash
docker stop gatelet-db
docker rm gatelet-db
```

For development inside the Codex devcontainer, run `experimental/gatelet/setup.sh` from the repository root before network access is disabled.

### Administration

Common management tasks are wrapped in a small `Makefile`:

```bash
make -C experimental/gatelet reset-db        # initialize a fresh database
make -C experimental/gatelet change-password # change the admin password
```

`reset-db` displays the current row counts for all tables and asks for confirmation before dropping everything. It then creates a fresh admin account with password `gatelet`.

### Testing and Development

Install the project with development dependencies and run tests using `pytest`.
When `IS_CODEX_ENV=1` is set, the test suite automatically launches a temporary
PostgreSQL server and removes it after the tests finish.

```bash
pip install -e '.[dev]'
pytest experimental/gatelet
```

Before committing, run:

```bash
pre-commit run --files <changed files>
```

## LLM-Friendly Design

Designed for current LLM constraints (as of May 2025), particularly OpenAI scheduled tasks with o3 model:

- Navigation entirely link-based (no forms, inputs, or JavaScript)
- Authentication via URL paths or challenge-response
- All functionality accessible via GET requests
- Self-describing interfaces guide LLMs on service usage

### OpenAI o3 Model Constraints

- Can execute Python code but cannot access URLs computed in Python
- Can only navigate to URLs explicitly given by users or links from pages
- Cannot use cookies or maintain browser state between page loads
- Cannot execute JavaScript or submit forms

## Authentication Methods

Gatelet supports multiple authentication methods:

1. **Key in Path** - Simple authentication by including key in URL path
   - Usage model: User provides direct URL with embedded key (http://server/k/SECRET_KEY/)
   - Example: `/k/{key}/` 

2. **Challenge-Response** - Secure authentication using nonce challenges
   - Usage model: User provides base URL and secret key separately
   - LLM visits base URL, receives challenge, computes answer with Python
   - Server presents multiple link options (no URL computation needed)
   - LLM selects correct link from options based on computation
   - Incorrect selection invalidates the challenge
   - Success grants session with time-limited links

3. **Human Admin Authentication** - Standard username/password for human administrators
   - Uses cookies for session management
   - Provides access to logs, session management, and key administration

## Authentication and Session Terms

- **Pre-Shared Key (PSK)**: Secret value known to both server and LLM, never transmitted directly
- **Challenge**: Unique problem requiring PSK to solve, regenerated for each authentication attempt
- **Nonce**: Single-use random value ensuring challenges can't be replayed
  - Includes embedded timestamp to ensure freshness
  - Server tracks used nonces to prevent replay attacks
  - Server rejects nonces older than a configured time window
- **Session**: Authenticated period allowing access to protected resources
  - **Session Token**: Unique identifier embedded in page links
  - **Session Extension**: Every link clicked extends session by 5 minutes
  - **Session Duration Cap**: Maximum 1-hour lifetime even with continuous use
  - **Session Expiration**: Occurs after 5 minutes of inactivity

## Features

### Webhooks
- Receive and store webhooks from various sources
- View webhook history with pagination
- Optional encryption for sensitive data

### Home Assistant Integration
- Current state of configured entities
- Historical state changes for discrete entities
- Trend data for continuous sensors (temperature, humidity, etc.)

### Session Management
- Challenge-based authentication for LLMs
- Time-limited tokens with automatic extension
- Human admin interface for viewing sessions, managing keys, and monitoring logs

## Implementation Plan

The project is implemented in phases:

1. **Phase 1** – Webhooks with Key‑in‑Path Authentication *(completed)*
   - Basic FastAPI server and PostgreSQL schema
   - Webhook receiving and storage
   - Key‑in‑path authentication

2. **Phase 2** – Challenge‑Response Authentication *(completed)*
   - Nonce‑based login flow for LLMs
   - Session management with automatic extension

3. **Phase 3** – Home Assistant Integration *(pending)*
   - Home Assistant API client
   - Entity state and history views

4. **Phase 4** – Human Admin Interface *(in progress)*
   - Password‑based admin login (implemented)
   - Dashboard with session and key management

## Current Status

Gatelet runs with both key‑in‑path and challenge‑response authentication.
Webhooks can be received and browsed, and a minimal password-based admin login
is available. Home Assistant integration and full admin dashboards are still
missing. See `TODO.md` in the repository root for the remaining tasks.
