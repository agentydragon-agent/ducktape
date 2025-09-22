# adgn

Local tools and libraries for my dev/worktree/LLM workflows.

- Worktree tools (wt): local server/CLI for git worktrees + GitHub display
- Tana export: convert Tana JSON dumps to Markdown/TanaPaste
- LLM utilities: MiniCodex client/UI, properties/specimens, system rewriter, etc.

Environment and setup (direnv + devenv)
- Requirements: Nix + devenv, direnv; Python 3.11+
- First time here:
  - cd /Users/mpokorny/code/ducktape/adgn
  - direnv allow
  - This loads .envrc → devenv, creates a Python venv, and installs the package in editable mode with dev extras.
- With devenv active, dev tools are on PATH automatically (pytest, ruff, pre-commit, wt, rspcache, …). Run them directly without prefixes when inside adgn/.
- Running from outside this dir (or scripts): prefix commands with direnv exec adgn …

Quick commands
- Run all tests (tests live under adgn/tests):
  - Inside adgn/: pytest tests
  - From repo root: direnv exec adgn pytest adgn/tests
- Single test file/case:
  - pytest tests/wt/integration/test_cli_integration.py
  - pytest tests/tana_export/test_convert.py::test_node_export
- Lint/format:
  - ruff format .
  - ruff check . --fix
- Pre-commit hooks (optional in this subpackage):
  - pre-commit install
  - pre-commit run -a
- Optional extras:
  - python -m pip install -e '.[gnome]'  # GNOME console script deps (system libs required)
- Build a wheel/sdist (optional):
  - python -m pip install build; python -m build

Console scripts
- wt → wt.cli:main
- wt-install → wt.shell.install:main
- rspcache → adgn.rspcache.cli:main
- switch_gnome_terminal_profile → adgn.gnome.switch_gnome_terminal_profile:run
- LLM: adgn-mini-codex, adgn-llm-edit, adgn-sysrw, adgn-properties, sandbox-jupyter-mcp

More details
- See ./CLAUDE.md for a deeper guide (test config, module map, LLM toolkit notes).