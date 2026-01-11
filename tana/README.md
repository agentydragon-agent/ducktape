# Tana Export Toolkit

Utilities for transforming Tana JSON exports into Markdown or TanaPaste formats and for
materialising saved searches. The package bundles CLI helpers plus a reusable library of
parsers/renderers under the `tana.export` namespace.

## Getting Started

```bash
cd tana
direnv allow        # loads devenv, creates a uv-managed venv
uv sync --extra dev # install runtime + dev dependencies

# Run the main conversion CLI
uv run tana-export-convert --help

# Execute tests
uv run pytest

# Linting and type checking
uv run ruff check .
uv run mypy
```

Key layout (`tana/`):

- `domain/` — data models, constants, and type definitions.
- `graph/` — `TanaGraph` workspace representation and structural helpers.
- `query/` — read/query helpers (filters, search parser/evaluator/materializer).
- `render/` — Markdown/TanaPaste formatting utilities.
- `io/` — JSON loaders (`load_workspace`).
- `export/` — CLI entry points and higher-level workflows.

Tests are under `tests/` with golden fixtures in `tests/tana/testdata/`.
