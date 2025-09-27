# WT Refactor Plan (Q3 2025)

Scope
- Focus areas: adgn/wt server + client reliability, GitHub PR cache/refresh, watchers, handlers, and view rendering. LLM-adjacent edits included only where they affect notifications or import hygiene.
- Out of scope: major feature work; protocol shape changes; persistence.

Status summary (current branch)
- Completed
  - GitHub PR list construction uses Pydantic field names (head_ref_name, merged_at ISO) — src/adgn/wt/server/github_client.py
  - PRService catches GitHubUnavailableError; uses asyncio.get_running_loop — src/adgn/wt/server/pr_service.py
  - GitHub refresh watcher stop is non-blocking via asyncio.to_thread — src/adgn/wt/server/github_refresh.py
  - Removed double initial refresh; single deterministic cache fill at startup — src/adgn/wt/server/github_refresh.py + src/adgn/wt/server/pr_service.py
  - Background task exception logging via _log_task_done; import hygiene — src/adgn/wt/server/handlers/status_handler.py
  - Tests: removed dead PyGithub shadow code; robust PR fixtures via WT_TEST_MODE — tests/wt/e2e/test_github_pr_display_real.py
  - Repo-wide strict import cleanup (moved non-optional/logging imports to top), fixed logger usage; LLM notifications tests passing

- Observations
  - Current design of PR cache and refresh is sound after the above, with reduced risk of silent task failures and startup races.

Prioritized tasks (with acceptance criteria)

P0 (none outstanding)
- All previously P0 issues are addressed. Keep an eye on PR list consumers when merged_at becomes non-null; add tests if new consumers appear.

P1 — Reliability/maintainability
1) Narrow boundary exception where feasible; improve diagnostics
   - File: src/adgn/wt/server/github_client.py (repo property)
   - Action: Catch provider/library exceptions explicitly (e.g., GithubException) if importable; otherwise retain boundary catch with logger.exception (already added).
   - Acceptance: When GitHub API is unavailable/401, logs include stack + repo; callers see GitHubUnavailableError; no broad catches outside this boundary.

3) Background tasks: unify done-callback pattern across server handlers
   - File: src/adgn/wt/server/handlers/status_handler.py and any other places creating background asyncio tasks
   - Action: Use _log_task_done consistently; search for add_done_callback(lambda...) and replace.
   - Acceptance: Grep shows only _log_task_done usage; injected failures log exceptions once and do not leak tasks into _bg_tasks.

P2 — UX/polish and tests
4) PR hyperlink to actual GitHub URL when configured
   - File: src/adgn/wt/client/view_formatter.py
   - Action: If config.github_repo is set, render https://github.com/{owner_repo}/pull/{n}; fallback to go/pull otherwise. Thread through a formatter helper if needed.
   - Acceptance: Links clickable to real PRs in integration tests; fallback preserved when repo not set.

5) Comments and tiny docs
   - Files:
     - src/adgn/wt/client/view_formatter.py: add one-line note that merged_at distinguishes merged vs closed
     - src/adgn/wt/server/pr_service.py: brief docstring on WT_TEST_MODE fixture behavior
   - Acceptance: Comments present, concise, accurate; help future maintainers.

6) Test coverage tweaks
   - Add a unit test for GitHubInterface.pr_list that asserts field names and merged_at serialization.
   - Add a resilience test to simulate GitHubUnavailableError and assert PRService.cached is PRCacheError without task crash.
   - Acceptance: New tests pass; fail when regressions are reintroduced.

Tooling guardrails (lint/semgrep)
- Semgrep rules (repo-level):
  - pydantic-v2-alias-constructor: Forbid alias kwargs (e.g., headRefName, mergedAt) in Pydantic constructors.
  - asyncio-get_running_loop-in-async: Flag get_event_loop() inside async defs.
  - broad-except-non-boundary: Flag broad except outside clearly marked boundaries with logger.exception.
- Ruff: Ensure import-at-top and import order; flag unused imports.
- Acceptance: Rules added in a separate housekeeping PR; zero new violations after autofix.

Risk assessment
- Low risk: Most changes are localized; protocols unchanged. Watch for any external callers of pr_list or view_formatter link generation.

Rollout plan
- Land this branch with tests green (wt + LLM subsets verified).
- Follow with a small PR for P1 #2/#3 (param/documentation cleanup + unified bg task callbacks).
- Then a UX polish PR for link rendering and comments (P2 #4/#5).
- Add Semgrep/Ruff rules in a final housekeeping PR.

Progress log (append-only)
- 2025-09-23: Initial pass — applied P0 fixes, removed double refresh, added exception logging, import cleanup; tests green (wt: 71 passed, LLM subset: 73 passed).
