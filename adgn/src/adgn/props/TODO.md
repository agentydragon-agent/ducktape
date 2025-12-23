# TODO

## General TODOs

- Potential indexing (property ↔ specimen cross-refs) if/when scale requires it
- Policy question: If an ABC's method docstring is repeated verbatim by an implementing subclass method, should this violate no-useless-docs? Lean yes, but leave undecided for now; reasonable people may disagree. Track under properties/no-useless-docs.md
- Windows/locale encodings: keep encoding="utf-8" for read_text/write_text to avoid surprises. TODO: I hate this.
- Target Python version detection/guidance: how agents/graders/reviewers determine target (crawl pyproject.toml/tooling, parse runtime markers, else infer from code/CI); decide where this lives in the framework.
- Property naming mismatch: 'self-describing names' vs guidance 'use datetime for datetimes'. Decide: either scope the property strictly to naming/units and create a separate 'time APIs and units' property (datetime vs time.monotonic, absolute vs interval), or rename/split. Update specimens and docs accordingly.

## Database/Schema TODOs

- Add optional per-range note/context field (models/true_positive.py)

## Testing TODOs

- Make specimen acquisition credential-free; currently depends on local GitHub creds (tests/props/cli/test_eval_lint_issue_wt.py)
  - Switch to token/codeload or vendored LocalSource for 2025-09-02-ducktape_wt specimen
- Add evaluation test cases from actual snapshots (eval_harness.py)

## Code Quality/Refactoring TODOs

- Deduplicate Docker container creation logic with docker_env.py and MCP server wiring (cli/cmd_snapshot.py)

## Feature TODOs

- Reimplement `fix` command as critic-driven loop:
  1. Run critic on workspace to find issues
  2. Fix flagged issues with rw-mounted workspace
  3. Rerun critic to verify fixes and catch any new issues
  4. Loop until critic finds no issues or max iterations reached

## Migration TODOs

- Bridge: accept (IssueCore, Occurrence) now; migrate to IssueDoc (lint_issue.py)
