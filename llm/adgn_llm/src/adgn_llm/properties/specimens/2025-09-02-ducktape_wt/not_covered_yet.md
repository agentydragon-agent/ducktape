## Dirty-state copy is never triggered

- Client only sends `source_branch`, so the daemon passes `None`; as a result, a dirty-state copy never happens.

## RPC surface: worktree identity contract

- `source_worktree` on the RPC violates the implicit contract that worktrees are identified by WorktreeID (opaque), not by alternative identifiers.

## Teleport resolution on client instead of server

- Client performs teleport resolution client-side rather than via the server, counter to the architectural intent.

## other

- wt/wt/server/git_manager.py: `log_format` ignores its `format_str` parameter and the only caller (`wt/wt/server/worktree_service.py`:62) immediately parses the string back. Replace with a structured return (no format+parse roundtrip).
- wt/wt/server/wt_server.py (_run_post_creation_script_streaming):
  - Return shape includes `ran` (always True) and `error` (always None) — remove redundant fields and signal errors via exceptions; return a structured result object.
  - Output forwarding collects stdout/stderr as lines with repeated `.decode(errors="replace")` and rejoins. Prefer reading raw bytes and either returning byte buffers or decoding once at the boundary; avoid lossy line-based decoding unless the consumer requires line semantics.
- wt/wt/shared/protocol.py:29–31 — Prefer `str.removeprefix("wtid:")` over slicing (`wtid[5:]`) for fixed-prefix removal (mirrors our Python convention).
- wt/tests/integration/test_shell_integration.py: prefer simple assertions over `pytest.fail(...)`; use `assert len(parts) == 5, f"Bad output: {s}"` at 229; assert non-empty `output_lines` at 156–157; apply the same assert style at ~163–164.
- Replace PR-shaped dicts with typed models:
  - Client rendering uses dicts with keys like `number`, `mergeable`, `additions`, `deletions` (wt/wt/client/view_formatter.py:109–125, 178–202, 295–306). Prefer `PRData` (from `shared/github_models.py`) and build hyperlinks/status from its fields.
  - Server builds ad-hoc PR dicts (wt/wt/server/wt_server.py:627, 629–630; 1070, 1072–1073). Prefer `GitHubPRResponse` → `coerce_prdata()` to `PRData`, and pass `PRData` through to the client. This removes key-typo risks and keeps field names consistent.

worktree_utils: create_worktree if/else has duplicated code, should first branch to identify source branch, then in shared trunk call create RPC.

in worktree_utils:
```python
def get_current_worktree_info(config) -> tuple[Path | None, str | None]:
    """Get current worktree information."""
    cwd = Path.cwd()
```
the function does not describe what either parameter is and it's not clear from the code either.
should either be documented in docstring or changed to return a descriptive dataclass/struct.
there is a general heuristic kinda like "do not return tuples/lists/... unless it's very clear what each member means".

## Duplication in GitHub PR info helpers
- wt/wt/server/wt_server.py: 595–637 (PRService.get_pr_info) duplicates logic with 997–1089 (_get_github_pr_info): PR search via executor, result dict assembly (number/title/state/draft/mergeable/merged_at/additions/deletions/html_url), and cache handling. Extract a shared helper (single fetch + serialization) and have both call it, or implement one in terms of the other to eliminate duplication.

## Test teardown pattern (wrapper yield fixture)
- wt/tests/conftest.py: 312–337, 370–371 — Prefer a wrapper yield fixture that handles daemon teardown automatically (kill before/after) instead of duplicating `kill_daemon_and_verify(...)` in setup and teardown.
- Candidate new property: "pytest-yield-fixtures-for-shared-teardown" — express shared setup/teardown via a yield fixture to avoid duplication and ensure correctness.

## Blocking I/O in async functions
- wt/wt/server/wt_server.py: 2501–2502 — Avoid synchronous file I/O inside async functions; if a blocking write is kept, at least use the concise Path form (`self.pid_file.write_text(...)`). Prefer non-blocking designs (e.g., to_thread) when feasible.

## kill_daemon_and_verify: further simplifications (not covered yet)
- wt/tests/conftest.py: 254–267 — Simplify the post-timeout verification: if `pid_file` still exists after deadline, fail immediately; avoid multi-branch relabeling.
- wt/tests/conftest.py: 258–265 — Shorten failure messages to concise one-liners; avoid verbose paragraphs in assertions.
- wt/tests/conftest.py: 192 — Remove the `timeout` parameter (use a constant or fixture-level setting); keep API minimal.
- wt/tests/conftest.py: 214–221 — Accept `wt_dir: Path` directly (domain: WT_DIR ≠ repo root); avoid recomputing from `repo_path`.
- Optional: verify PID changes across checks to detect daemon restarts during shutdown; unify process-existence and pid-file checks.

## Config construction surface-form rules (not covered yet)
- Prefer direct keyword arguments over dict merges like `**{**a, **b}` when both dicts are known at the callsite; improves readability and diffability.
- Prefer passing explicit kwargs to Pydantic models rather than assembling an intermediate kwargs dict when simple `a=b` is immediately available.
