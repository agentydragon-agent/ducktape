# AGENTS.md — Agent Guide for `tana`

Focused instructions for the Tana export toolkit that now lives as its own project.

## Environment

- Requirements: direnv + devenv (see `.envrc`) and Python 3.12+ managed by uv.
- First-time setup:
  - `cd tana`
  - `direnv allow`
  - `uv sync --extra dev`
- Standard commands (inside the project directory):
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run mypy`
  - Run the CLI: `uv run tana-export-convert --help`

## Package Layout (`src/tana/`)

- `domain/` — immutable data models (`Props`, `BaseNode`, `TupleNode`, …) and shared constants/types.
- `graph/` — `TanaGraph` workspace representation plus structural helpers (`wrappers`).
- `query/` — read/query utilities: field/filters, search parser/evaluator/materializer, tuple helpers.
- `render/` — HTML/inline reference handling used while rendering Markdown/TanaPaste.
- `io/` — loaders for JSON exports (`load_workspace`).
- `export/` — user-facing commands (conversion, node subset export, search materializer).

## Tests & Fixtures

- Tests live under `tests/`; existing suite focuses on conversion golden files.
  - `uv run pytest` (or `pytest` once direnv activates the env).
  - Golden fixtures stored in `tests/tana/testdata/`.

## Gotchas

- `TanaGraph` sets the `_graph` reference on nodes; avoid calling legacy `attach_supertag_property` helpers—supertags resolve via `node.supertags`.
- Prefer absolute imports (`tana.query.search_parser`, etc.) to keep layering clear.
- CLI scripts expect JSON dumps that mirror Tana’s export structure (`docs` array with node dicts).
