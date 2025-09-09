# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Scope: This document covers the adgn-llm Python package under llm/adgn_llm. It provides environment setup, common commands, and a high‑level map of the major modules so you can be productive quickly.

Environment and setup
- Requirements: Python 3.11+, uv (https://docs.astral.sh/uv/), pre-commit, Node.js (for system_rewriter templating), direnv (optional but recommended).
- Install deps with uv (editable, incl. dev extras):
  - cd /Users/mpokorny/code/ducktape/llm/adgn_llm
  - uv sync --extra dev
  - uv run pip install -e .
- direnv option (recommended): If an .envrc exists in this directory, direnv will auto-activate the project venv (devenv). In that case, you can run console scripts directly without `uv run`.
  - Example .envrc:
    - watch_file pyproject.toml uv.lock
    - source .venv/bin/activate
  - Then run: direnv allow
- OpenAI credentials (used by many tools/tests): export OPENAI_API_KEY=... (and any provider-specific env you use).

Common commands
- Lint + format (ruff configured in this package):
  - uv run ruff format .
  - uv run ruff check . --fix
- Run all tests (pytest config lives in this package’s pyproject):
  - uv run pytest -q
- Exclude live API tests by default:
  - uv run pytest -q -m "not live_llm"
- Run a single test:
  - uv run pytest -q tests/cli/test_llm_edit_cli.py::test_help
- Pre-commit (optional):
  - pre-commit run -a
- Build wheel/sdist:
  - uv build

CLIs provided by this package (installed via [project.scripts])
- adgn-llm-edit: lightweight local editing CLI.
- adgn-sysrw: system rewriter/eval toolkit orchestration.
- adgn-properties: property definitions/queries utilities.
- adgn-inop, adgn-mini-codex, sandbox-jupyter-mcp, adgn-sandboxer, adgn-mcp-* and git-commit-ai: additional tools used across workflows.

Quick usage examples
- System rewriter (requires Node; no npm deps; JS apply script performs exact {{...}} substitutions):
  - adgn-sysrw run \
    /Users/mpokorny/code/ducktape/llm/adgn_llm/src/adgn_llm/system_rewriter/templates/current_effective_template.txt
  - adgn-sysrw extract --source ccr
  - adgn-sysrw extract --source crush --scan-dir "$HOME/code"
  - adgn-sysrw compare /absolute/path/to/runs/<ts>
  - Tip: If not inside an activated devenv, prefix with `uv run`.
- LLM edit CLI:
  - adgn-llm-edit --help
- Properties search (example):
  - adgn-properties find /path/to/repo "all files under internal/app/**"

High-level architecture (big picture)
- adgn_llm.system_rewriter (src/adgn_llm/system_rewriter/...): End‑to‑end evaluation of rewritten system prompts.
  - CLI entry: adgn-sysrw (Typer app in src/adgn_llm/system_rewriter/cli.py)
  - Node renderer performs exact single-use {{...}} substitutions of tools/env/model/mcp blobs; Node must be available; no npm install is required. It requires extractSystemBlobs from js/lib/system-utils.js or ~/.claude-code-router/transformers/lib/system-utils.js.
  - Produces runs/<timestamp>/ with samples.jsonl, grades.jsonl, summary.json, report.html.
- adgn_llm.llm_edit (src/adgn_llm/llm_edit.py): Small helper CLI for local code/text editing tasks.
- adgn_llm.properties (src/adgn_llm/properties/...): Property definitions + CLI for codebase property discovery.
- adgn_llm.inop (src/adgn_llm/inop/...): Instruction optimizer components; async runners and iteration logic.
- adgn_llm.mcp (src/adgn_llm/mcp/...): MCP utilities/launchers (e.g., sandboxed Jupyter MCP).
- adgn_llm.mini_codex (src/adgn_llm/mini_codex/...): Minimal OpenAI API wrapper utilities used by other tools.

Notes and caveats
- Node requirement: The system_rewriter apply step is Node-only; no npm needed. The script src/adgn_llm/system_rewriter/js/system_rewrite_apply.js validates tokens and fails fast; missing Node or system-utils will cause a hard error.
- Test data/specimens under src/adgn_llm/properties/specimens/** are excluded from lint and test discovery per pyproject configuration.
