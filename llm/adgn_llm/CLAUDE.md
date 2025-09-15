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
- Code quality (preferred: pre-commit; see repo-root .pre-commit-config.yaml):
  - pre-commit install  # once per clone
  - pre-commit run -a   # runs Ruff lint/format, mypy, buildifier per config
  - Alternative: uv run ruff format .; uv run ruff check . --fix
- Run all tests (pytest config lives in this package’s pyproject):
  - uv run pytest -q
- Exclude live API tests by default:
  - uv run pytest -q -m "not live_llm"
- Exclude sandboxer suite and live API tests:
  - uv run pytest -q -m "not live_llm" -k "not sandboxed_jupyter_mcp"
- Run a single test:
  - uv run pytest -q tests/cli/test_llm_edit_cli.py::test_help
- Jsonnet specimens (not yet enforced by hooks; format after edits):
  - git ls-files "src/adgn_llm/properties/specimens/**/*.libsonnet" | xargs -r jsonnetfmt -i
  - or run under the project environment: direnv exec "$(pwd)" git ls-files "src/adgn_llm/properties/specimens/**/*.libsonnet" | xargs -r jsonnetfmt -i
  - Note: jsonnetfmt is provided by the devenv (uv sync --extra dev) and available via direnv.
- Build wheel/sdist:
  - uv build

Specimen inspection (for assistants)
- Use the specimen shell to safely inspect a specimen’s hydrated workspace inside an isolated container (no network):
  - Schema (Pydantic source of truth):
    - @src/adgn_llm/properties/models/specimen.py
    - @src/adgn_llm/properties/models/issue.py
  - Loader and hydration: @src/adgn_llm/properties/specimen_registry.py
  - NOTE: DO NOT duplicate examples or schema text here; the file above is transcluded as the single source of truth.
  - adgn-properties specimen-shell 2025-09-02-ducktape_wt
  - Or execute a one‑off command (after --). The workspace is mounted at /workspace and property definitions at /props.

Examples (read code with line numbers; search with ripgrep)
- Print a numbered range (nl + sed):
  - adgn-properties specimen-shell 2025-09-02-ducktape_wt -- sed -n '18,36p' /workspace/wt/wt/server/github_client.py
  - adgn-properties specimen-shell 2025-09-02-ducktape_wt -- nl -ba --number-width=6 --number-format=ln /workspace/wt/wt/shared/models.py | sed -n '130,170p'
- Search outside tests with ripgrep (rg is baked into the image):
  - adgn-properties specimen-shell 2025-09-02-ducktape_wt -- rg -n "WorktreeService\.create_worktree\(|execute_post_creation_script\(" /workspace/wt --glob '!/workspace/wt/tests/**'
- Multi‑line convenience via heredoc:
  - adgn-properties specimen-shell 2025-09-02-ducktape_wt -- bash -lc $'nl -ba /workspace/wt/wt/server/wt_server.py | sed -n \"220,240p\"; echo ---; sed -n \"2035,2060p\" /workspace/wt/wt/server/wt_server.py'

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
- adgn_llm.sysrw (src/adgn_llm/sysrw/...): End‑to‑end evaluation of rewritten system prompts.
  - CLI entry: adgn-sysrw (Typer app in src/adgn_llm/sysrw/cli.py)
  - Node renderer performs exact single-use {{...}} substitutions of tools/env/model/mcp blobs; Node must be available; no npm install is required. It requires extractSystemBlobs from js/lib/system-utils.js or ~/.claude-code-router/transformers/lib/system-utils.js.
  - Produces runs/<timestamp>/ with samples.jsonl, grades.jsonl, summary.json, report.html.
- adgn_llm.llm_edit (src/adgn_llm/llm_edit.py): Small helper CLI for local code/text editing tasks.
- adgn_llm.properties (src/adgn_llm/properties/...): Property definitions + CLI for codebase property discovery.
- adgn_llm.inop (src/adgn_llm/inop/...): Instruction optimizer components; async runners and iteration logic.
- adgn_llm.mcp (src/adgn_llm/mcp/...): MCP utilities/launchers (e.g., sandboxed Jupyter MCP).
- adgn_llm.mini_codex (src/adgn_llm/mini_codex/...): Minimal OpenAI API wrapper utilities used by other tools.

Tests and directory layout
- Test files live under this package’s tests/ tree, not under src/.
- Mirror the src/ structure for discoverability (e.g., tests/mini_codex for src/adgn_llm/mini_codex).
- Use the package-local pytest config in pyproject.toml when running from here. Typical invocations:
  - uv run pytest -q
  - uv run pytest -q -m "not live_llm"
  - uv run pytest -q -m "not live_llm" -k "not sandboxed_jupyter_mcp"

Notes and caveats
- Node requirement: The system_rewriter apply step is Node-only; no npm needed. The script src/adgn_llm/system_rewriter/js/system_rewrite_apply.js validates tokens and fails fast; missing Node or system-utils will cause a hard error.
- Test data/specimens under src/adgn_llm/properties/specimens/** are excluded from lint and test discovery per pyproject configuration.
- when running tests in this package (adgn_llm), skip the sandboxer suite on macOS unless you’re explicitly working on it; use:
  - uv run pytest -q -m "not live_llm" -k "not sandboxed_jupyter_mcp"

@instructions/jsonnet_authoring.md
@instructions/fastmcp_pydantic.md
@instructions/fastmcp_exceptions.md
