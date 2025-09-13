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
- Exclude sandboxer suite and live API tests:
  - uv run pytest -q -m "not live_llm" -k "not sandboxed_jupyter_mcp"
- Run a single test:
  - uv run pytest -q tests/cli/test_llm_edit_cli.py::test_help
- Pre-commit (optional):
  - pre-commit run -a
  - Format Jsonnet specimens after editing (recommended):
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

Jsonnet authoring guidelines (||| blocks and issue files)

- Location and shape
  - All specimen issues live under: src/adgn_llm/properties/specimens/<specimen>/issues/*.libsonnet
  - Each file is ONE standalone Jsonnet expression that returns a single Issue object built via helpers from specimen_issues.libsonnet
  - Start every file with: `local I = import '../../specimen_issues.libsonnet';`
  - File name must equal the issue id (e.g., issues/iss-032.libsonnet). Do not include id in the Jsonnet; the loader derives it from the filename.

- Triple-bar text blocks (|||) — exact house style
  - Opening delimiter: exactly one space before it
    - Good: `rationale= |||`
    - Bad:  `rationale=|||` (no space) or extra spaces
  - Content lines: indent every line by exactly two spaces
  - Closing delimiter: two spaces + `|||,` on its own line (include the comma there)
  - Full correct pattern:
    ```jsonnet
    I.issueOneOccurrence(
      rationale= |||
        First line of rationale...
        Second line...
      |||,
      properties=['some-prop'],
      filesToRanges={ 'path/to/file.py': [[10, 20]] },
    )
    ```
  - Common failures we saw and fixes:
    - Missing closing: add the `|||,` line (two-space indent)
    - Comma on a separate line: move the comma to the closing `|||,` line
    - Ragged indent inside: normalize all content lines to two spaces
    - Closing indented differently than content: use the same two-space indent

- Choosing the right constructor (and where notes go)
  - One logical occurrence spanning multiple files/ranges → use `I.issueOneOccurrence(rationale, filesToRanges=...)`
    - If you want commentary for specific ranges, put those sentences into the rationale text (bulleted or paragraph form). Do NOT put notes inside ranges for filesToRanges.
  - Many independent occurrences (each can have its own note) → use `I.issueWithOccurrences(rationale, occurrences=[{ files: {...}, note: '...' }, ...])` or `I.issueOccurrencesFromLines(rationale, linesByFile={ ... })`
    - `issueWithOccurrences` supports per-occurrence `note` strings.
    - `issueOccurrencesFromLines` supports shorthand entries (numbers, [start,end], or strings to serve as occurrence-level notes on unspecified ranges).

- Valid range specs by helper
  - filesToRanges (for `issueOneOccurrence`):
    - Allowed per-file entries: `null` (unspecified), `[]` (unspecified), `[line]` (single), `[start,end]` (span), or objects `{ start_line: n, end_line?: m }`
    - NOT allowed: tuples with strings (e.g., `[137, 143, 'note']` or `[133, 'why']`) — move such note text into the rationale (bullet per file/lines)
  - linesByFile (for `issueOccurrencesFromLines`):
    - Allowed per-file entries: numbers, `[start,end]`, strings (become occurrence-level note with unspecified range), or `{range: <spec>, note: '...'}`

- Import/search path
  - Always import helpers via a relative path from the issues/ directory: `local I = import '../../specimen_issues.libsonnet';`
  - Loader sets the library path; do not chdir or edit imports in-place.

- Trailing commas & monolith split
  - Each issue file is a standalone expression; remove aggregator-style trailing commas at the end of the expression.
  - Keep commas only between arguments and after the closing `|||` line.

- Quick examples of wrong vs right (|||)
  - Wrong (comma alone after closing):
    ```jsonnet
    rationale= |||
      Text
    |||
      ,
    ```
  - Right:
    ```jsonnet
    rationale= |||
      Text
    |||,
    ```
  - Wrong (no closing):
    ```jsonnet
    rationale= |||
      Text
    ,
    ```
  - Right (balanced):
    ```jsonnet
    rationale= |||
      Text
    |||,
    ```

Notes and caveats
- Node requirement: The system_rewriter apply step is Node-only; no npm needed. The script src/adgn_llm/system_rewriter/js/system_rewrite_apply.js validates tokens and fails fast; missing Node or system-utils will cause a hard error.
- Test data/specimens under src/adgn_llm/properties/specimens/** are excluded from lint and test discovery per pyproject configuration.
- when running tests in this package (adgn_llm), skip the sandboxer suite on macOS unless you’re explicitly working on it; use:
  - uv run pytest -q -m "not live_llm" -k "not sandboxed_jupyter_mcp"