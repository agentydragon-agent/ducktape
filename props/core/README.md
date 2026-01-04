# Props Core

Core library for the Props evaluation framework.

## Development Setup

### Prerequisites

Tests require a running PostgreSQL database. The easiest way to set this up is using the devenv environment:

```bash
# Install Nix and devenv (if not already installed)
# See: https://devenv.sh/getting-started/

# Enter the development environment (sets up PostgreSQL)
cd props/core
direnv allow  # Activates .envrc which loads devenv
```

The devenv environment automatically:

- Starts a local PostgreSQL server
- Sets the required `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` environment variables
- Creates a virtual environment with all dependencies

### Running Tests

**With devenv (recommended):**

```bash
cd props/core
direnv allow  # If not already done

# Run all tests
pytest

# Run specific test file
pytest tests/test_agent_types.py -v

# Run with parallel execution
pytest -n auto
```

**Manual setup (without devenv):**

If you can't use devenv, you need to:

1. Install and start PostgreSQL
2. Set environment variables:
   ```bash
   export PGHOST=localhost
   export PGPORT=5432
   export PGUSER=postgres
   export PGPASSWORD=your_password
   export PGDATABASE=postgres
   ```
3. Run tests with Bazel:
   ```bash
   bazel test //props/core:test_props_core
   ```

### Test Organization

- `tests/db/` - Database layer tests (models, queries, views)
- `tests/grader/` - Grading logic tests (matching, credit calculation)
- `tests/critic/` - Critique submission tests
- `tests/cli/` - CLI command tests
- `tests/gepa/` - GEPA optimizer tests
- `tests/prompt_optimize/` - Prompt optimization tests
- `tests/prompt_improve/` - Prompt improvement tests

### CI

Tests are automatically run in GitHub Actions for all commits and pull requests.
See `.github/workflows/ci.yml` for the full CI configuration.
