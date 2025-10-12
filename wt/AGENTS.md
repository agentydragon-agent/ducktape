# AGENTS.md — Agent Guide for `wt`

Helpful pointers for working on the `wt` worktree manager: environment, commands, testing, layout, and gotchas. Read alongside `README.md` for product docs and `docs/ARCHITECTURE.md` for in-depth design notes.

## Environment and Tooling
- Requirements: Nix + devenv, direnv, Python **3.11**+. `gitstatusd` must be installed separately for integration tests.
- First time setup:
  1. `cd wt`
  2. `direnv allow`
  3. Direnv loads `.envrc`, which bootstraps devenv and installs `wt` in editable mode with the `dev` extras via `uv`.
- Environment checks (inside `wt/`):
  - `direnv status` shows whether the env is active.
  - `echo "$VIRTUAL_ENV"` → `/wt/.devenv/state/venv`
  - `which python` → the same venv bin directory.
  - Helper scripts registered via devenv: `wt-tests`, `wt-lint`, `wt-typecheck`.
- Refresh the environment after changing `devenv.nix`, `.envrc`, `pyproject.toml`, or `uv.lock`: run `direnv reload`.

### Extra dependencies / binaries
- `libgit2`, `pkg-config`, and `git` are provided via devenv.
- `gitstatusd` **is not bundled**; install it separately and ensure it is on `PATH` (`which gitstatusd`). Without it, daemon/integration tests fail quickly.

## Common Development Commands
- Run the CLI entry point: `wt --help` (works from within the environment).
- Tests:
  - Full suite: `wt-tests` (alias for `uv run pytest`).
  - Focused: `pytest tests/<file>::<test>` as usual.
  - Integration tests marked `integration` or `shell` spawn git repos and daemons; they may need relaxed sandboxing to allow UNIX sockets and filesystem operations.
- Linting and type checking:
  - `wt-lint` (`uv run ruff check .`)
  - `wt-typecheck` (`uv run mypy src tests`)
  - Format (if needed): `uv run ruff format .`
- From the repo root, you can run commands via direnv: `direnv exec wt pytest tests/test_cli.py`.

## Project Structure (src layout)
- `src/wt/cli.py` — CLI entry point (`wt` console script).
- `src/wt/client/` — CLI-side handlers, socket client, shell helpers.
- `src/wt/server/` — Background daemon, gitstatusd integration, worktree service logic.
- `src/wt/shared/` — Shared models, protocol definitions, constants.
- `src/wt/shell/` — Shell integration (`wt.sh`, installer).
- `tests/` — Pytest suite with fixtures for git repos, config factories, daemon/server tests.
- Additional docs: `docs/ARCHITECTURE.md`, `docs/SPLIT_FEATURE_DESIGN.md`, `docs/WORKTREE_IDEAS.md`.

## Testing and Markers
- Pytest configuration lives in `pyproject.toml`.
- Markers you will see:
  - `unit` — fast tests, no external processes.
  - `integration` — touches git repos/daemons.
  - `shell` — exercises fd3 shell integration (requires real shell support).
  - `real_github` — requires network access to GitHub (skipped by default).
  - `asyncio`, `slow` — opt-in markers for more specialized cases.
- Default addopts (already configured): `-m "not real_github" -v --tb=short --strict-markers --disable-warnings --timeout=30`.

## Operational Notes / Pitfalls
- The CLI communicates with a daemon via UNIX sockets. Tests that cover this path need filesystem + socket permissions; in restricted sandboxes those calls may fail with ECONNREFUSED or bind errors.
- Hooks and shell integration rely on fd3 semantics; avoid breaking this when modifying `wt.shell` utilities.
- `gitstatusd` metrics are surfaced to the client; when altering daemon startup flows, ensure `gitstatusd_listener` lifecycle stays in sync.
- Copy-on-write behavior differs per platform (clonefile vs reflink vs rsync). Keep feature flags configurable through the shared config models.

## Related Resources
- Top-level repository overview: `../AGENTS.md`
