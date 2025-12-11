# TODO

## General TODOs

- Potential indexing (property ↔ specimen cross-refs) if/when scale requires it
- Policy question: If an ABC's method docstring is repeated verbatim by an implementing subclass method, should this violate no-useless-docs? Lean yes, but leave undecided for now; reasonable people may disagree. Track under properties/no-useless-docs.md
- Windows/locale encodings: keep encoding="utf-8" for read_text/write_text to avoid surprises. TODO: I hate this.
- Target Python version detection/guidance: how agents/graders/reviewers determine target (crawl pyproject.toml/tooling, parse runtime markers, else infer from code/CI); decide where this lives in the framework.
- Property naming mismatch: 'self-describing names' vs guidance 'use datetime for datetimes'. Decide: either scope the property strictly to naming/units and create a separate 'time APIs and units' property (datetime vs time.monotonic, absolute vs interval), or rename/split. Update specimens and docs accordingly.

## Codex Property Enforcer and Analyzer

Observation (to investigate)
- Enforcer added a local import justification in a test that already imports the module at top of file.
  - File: project/ditto/ditto_chat/ditto_chat/tools/tests/test_sandboxed_shell_tool.py
  - Symptom: Inserted a comment asserting "Local import in test to avoid heavy module import … heavy import justified," but a top-level import for the same module already exists.
  - Action: Re-run against this file with a "find-only" analyzer and ask whether the state is correct; capture the agent's argument.

## CLI consolidation TODOs

- Unify specimen-discover into the `run` command
  - Add `--embed-specimen-notes` to `run` (specimen mode) to auto-embed `covered.md` and `not_covered_yet.md` as supplemental context.
  - For structured runs, keep the critic_submit gating; for `--dry-run`, render with minimal wiring and save the prompt like other presets.
  - Remove the `specimen-discover` command after migration; update docs to use:
    - `adgn-properties run --snapshot <slug> --preset discover --structured true --embed-specimen-notes`
  - Tests: port any `specimen-discover` dry-run tests to run with `--preset discover --dry-run --embed-specimen-notes`.

## Database/Schema TODOs

- Add critic_scope_id FK to critic_scopes table to track which scope was used (db/models.py)
- Decouple DB state and MCP I/O shapes so database models can have sensible defaults (models/true_positive.py)
- Add optional per-range note/context field (models/true_positive.py)

## Testing TODOs

- Make specimen acquisition credential-free; currently depends on local GitHub creds (tests/props/cli/test_eval_lint_issue_wt.py)
  - Switch to token/codeload or vendored LocalSource for 2025-09-02-ducktape_wt specimen
- Add evaluation test cases from actual snapshots (eval_harness.py)

## Code Quality/Refactoring TODOs

- Refactor display config threading; currently verbose and max_lines are passed through multiple layers (agent_setup.py)
- Clean up path propagation; reviewed_files is extracted and passed through unnecessarily (grader/grader.py)
- Deduplicate Docker container creation logic with docker_env.py and MCP server wiring (cli/cmd_snapshot.py)
- Auto-infer prompt_optimization_run_id in MCP server tools instead of manually passing it (prompt_optimize/prompt_optimizer.py)

## Migration TODOs

- Bridge: accept (IssueCore, Occurrence) now; migrate to IssueDoc (lint_issue.py)
- Migrate git tags from specimen-* to snapshot-* prefix (if still relevant for remote repos)
