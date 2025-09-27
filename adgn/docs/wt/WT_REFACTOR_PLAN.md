# WT Refactor Plan — Outstanding Work Only

This document lists only the remaining work items for `adgn.wt`.

Outstanding Tasks (with acceptance criteria)

P1 — Reliability/maintainability
1) Narrow boundary exceptions; improve diagnostics
   - File: `src/adgn/wt/server/github_client.py` (repo property)
   - Action: Catch provider/library exceptions explicitly (e.g., GithubException) if importable; otherwise retain boundary catch with logger.exception.
   - Acceptance: When GitHub API is unavailable/401, logs include stack + repo; callers see GitHubUnavailableError; no broad catches outside this boundary.

2) Unify background task done-callback pattern
   - Files: `src/adgn/wt/server/handlers/status_handler.py` and any modules creating background asyncio tasks
   - Action: Use `_log_task_done` consistently; replace `add_done_callback(lambda...)` usages.
   - Acceptance: Grep shows only `_log_task_done`; injected failures log exceptions once and do not leak tasks into `_bg_tasks`.

P2 — UX/polish and tests
3) PR hyperlink to actual GitHub URL when configured
   - File: `src/adgn/wt/client/view_formatter.py`
   - Action: If `config.github_repo` is set, render `https://github.com/{owner_repo}/pull/{n}`; fallback to `go/pull` otherwise.
   - Acceptance: Links clickable to real PRs in integration tests; fallback preserved when repo not set.

4) Comments and tiny docs
   - Files:
     - `src/adgn/wt/client/view_formatter.py`: note that `merged_at` distinguishes merged vs closed
     - `src/adgn/wt/server/pr_service.py`: brief docstring on `WT_TEST_MODE` fixture behavior
   - Acceptance: Comments present, concise, accurate.

5) Test coverage tweaks
   - Add a unit test for `GitHubInterface.pr_list` that asserts field names and `merged_at` serialization.
   - Add a resilience test to simulate `GitHubUnavailableError` and assert `PRService.cached` is `PRCacheError` without task crash.
   - Acceptance: New tests pass; fail on regression.

Tooling guardrails (lint/semgrep)
- Semgrep rules (repo-level):
  - `pydantic-v2-alias-constructor`: Forbid alias kwargs (e.g., headRefName, mergedAt) in Pydantic constructors.
  - `asyncio-get_running_loop-in-async`: Flag `get_event_loop()` inside async defs.
  - `broad-except-non-boundary`: Flag broad `except` outside clearly marked boundaries with `logger.exception`.
- Ruff: Ensure import-at-top and import order; flag unused imports.
- Acceptance: Rules added in a housekeeping PR; zero new violations after autofix.

Rollout plan
- Small PR for P1 tasks (#1, #2)
- Follow with P2 polish/tests (#3–#5)
- Add Semgrep/Ruff rules in a final housekeeping PR
