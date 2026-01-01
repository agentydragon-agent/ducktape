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

### Test database access

If the env var `IS_CODEX_ENV` is set to `1`, you are running in a Codex container
and MUST make tests bring up **AND** TEAR DOWN the database before & at the end
of your test commands. If you fail to tear it down properly, it violates the
Codex environment check that no processes may linger between execution steps.
MAKE SURE TO CREATE AND TEAR DOWN THE DATABASE AND START/STOP THE SERVER IN
YOUR TESTS.

Example:

```python
# conftest.py
import subprocess, os, pytest, tempfile, shutil, time

@pytest.fixture(scope="session", autouse=True)
def _postgres():
    if os.environ.get("IS_CODEX_ENV") != "1":
        yield
        return

    datadir = tempfile.mkdtemp()
    subprocess.check_call(["initdb", "-D", datadir, "-A", "trust"])
    proc = subprocess.Popen(["pg_ctl", "-D", datadir, "-w", "start"])
    os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres@localhost/postgres"
    time.sleep(0.5)          # tiny grace
    try:
        yield
    finally:
        subprocess.check_call(["pg_ctl", "-D", datadir, "-m", "fast", "stop"])
        shutil.rmtree(datadir)
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

Before committing, run linting:
```bash
bazel lint //gatelet:all
```

For non-Python checks (YAML, etc.), run:
```bash
pre-commit run --all-files
```

## Reporter Daemon

All data collection binaries are unified into ``gatelet-reporter``.  It reads
defaults from ``$XDG_CONFIG_HOME/gatelet/gatelet-report.toml``. Running
``gatelet-reporter`` launches a daemon that periodically reports battery status
when ``battery_enabled = true`` in the config.  Use ``gatelet-reporter event``
to send one-off events. Future reporters should reuse this binary rather than
adding new entry points.

## Run environment

If you are OpenAI Codex, you are probably running in an environment that has no internet
access, but was previously initialized by running `gatelet/setup.sh` from repo root before
internet access was turned off.

If you need to add a new dependency, set it up to be installed by the `gatelet/setup.sh` script.
You will not be able to install it yourself, but you will help by giving the commands
needed to install it for future runs.

## Template Guidelines

Each HTML template begins with a comment describing its intended audience:

- `human admin`
- `LLM`
- `authenticated human admin or LLM`

Pages for LLMs must offer only link-based navigation and avoid forms or other
interactive elements so models can follow them reliably.

## Project Status

Key-in-path and challenge-response authentication are implemented and webhook
handling works. The admin login, key management, session overview and log pages
are all functional. Home Assistant entity states list friendly names and, when
viewed by a human admin, include links back to the Home Assistant UI using the
configured API URL. Refer to
`gatelet/TODO.md` for remaining tasks such as history and trend views.
