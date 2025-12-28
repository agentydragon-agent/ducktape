# Props Core

Core library for the Props evaluation framework.

## Development Setup

### Running Tests

Tests require a local virtual environment with development dependencies:

```bash
cd props/core

# Create virtual environment
uv venv --python=python3.12 .venv

# Activate virtual environment
source .venv/bin/activate

# Install with dev and orchestration extras
uv pip install -e ".[dev,orchestration]"

# Run all tests
pytest

# Run specific test file
pytest tests/test_agent_types.py -v

# Run with parallel execution
pytest -n auto
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
