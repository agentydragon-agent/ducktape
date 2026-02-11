# WT Refactor Plan

## Scope

- Focus areas: `wt` server + client reliability, GitHub PR cache/refresh, watchers, handlers, and view rendering.
- Out of scope: major feature work, protocol shape changes, persistence, or unrelated LLM tooling.

## Status Summary (current branch)

- Completed
  - GitHub PR list construction now uses Pydantic field names (`head_ref_name`, `merged_at` ISO) — `src/wt/server/github_client.py`
  - `PRService` catches `GitHubUnavailableError`; uses `asyncio.get_running_loop` — `src/wt/server/pr_service.py`
  - GitHub refresh watcher stop is non-blocking via `asyncio.to_thread` — `src/wt/server/github_refresh.py`
  - Removed double initial refresh; single deterministic cache fill at startup — `src/wt/server/github_refresh.py` + `src/wt/server/pr_service.py`
  - Background task exception logging via `_log_task_done`; import hygiene tightened — `src/wt/server/handlers/status_handler.py`
  - Tests: removed dead PyGithub shadow code; robust PR fixtures via `WT_TEST_MODE` — `tests/wt/e2e/test_github_pr_display_real.py`
  - Repo-wide strict import cleanup (moved non-optional/logging imports to top); LLM notifications tests passing

- Observations
  - Current PR cache + refresh design is sound after earlier fixes; remaining work is polish and guardrails.

## Outstanding Work (acceptance-oriented)

### P1 — Reliability / Maintainability

1. **Narrow boundary exceptions; improve diagnostics**
   File: `src/wt/server/github_client.py` (repo property)
   Action: Catch provider/library exceptions explicitly (e.g. `GithubException`) if available; otherwise keep boundary catch with `logger.exception`.
   Acceptance: GitHub API errors log stack+repo detail, callers receive `GitHubUnavailableError`, no broad catches outside the boundary.

2. **Unify background-task cleanup**
   Files: `src/wt/server/handlers/status_handler.py` and any modules creating background asyncio tasks
   Action: Replace `add_done_callback(lambda ...)` with `_log_task_done` consistently.
   Acceptance: Grep shows only `_log_task_done` callbacks; injected failures log once and do not leak tasks into `_bg_tasks`.

### P2 — UX / Polish / Tests

3. **PR hyperlinks respect configured repo**
   File: `src/wt/client/view_formatter.py`
   Action: When `config.github_repo` is set, emit `https://github.com/{owner_repo}/pull/{n}`; fall back to `http://go/pull/{n}` otherwise.
   Acceptance: Integration tests confirm clickable GitHub links; fallback remains when repo unset.

4. **Comments and micro-docs**
   Files:
     - `src/wt/client/view_formatter.py`: add note that `merged_at` drives merged-vs-closed label.
     - `src/wt/server/pr_service.py`: brief docstring on `WT_TEST_MODE` fixture behavior.
   Acceptance: Comments exist, are concise/accurate, and help future maintainers.

5. **Test coverage tweaks**
   - Add unit test for `GitHubInterface.pr_list` asserting field names and `merged_at` serialization.
   - Add resilience test simulating `GitHubUnavailableError`; ensure `PRService.cached` stores `PRCacheError` without task crash.
   Acceptance: New tests pass and fail appropriately on regressions.

### Tooling Guardrails (lint / Semgrep)

- Semgrep rules (repo-level) to add:
  - `pydantic-v2-alias-constructor`: forbid alias kwargs (`headRefName`, `mergedAt`) in constructors.
  - `asyncio-get_running_loop-in-async`: flag `get_event_loop()` inside async defs.
  - `broad-except-non-boundary`: flag broad `except` outside boundary sections with `logger.exception`.
- Ruff: ensure import-at-top and canonical order, catch unused imports.
- Acceptance: Rules land via housekeeping PR; repo lint passes with zero new violations.

## Rollout Plan

1. Small PR covering P1 tasks.
2. Follow-up PR for P2 UX/tests polish.
3. Final housekeeping PR enabling Semgrep/Ruff rules.

## Progress Log (append-only)

- 2025-09-23: Initial pass — applied P0 fixes, removed double refresh, added exception logging, import cleanup; tests green (wt: 71 passed, LLM subset: 73 passed).
