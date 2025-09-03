## Dirty-state copy is never triggered

- Client only sends `source_branch`, so the daemon passes `None`; as a result, a dirty-state copy never happens.

## RPC surface: worktree identity contract

- `source_worktree` on the RPC violates the implicit contract that worktrees are identified by WorktreeID (opaque), not by alternative identifiers.

## Teleport resolution on client instead of server

- Client performs teleport resolution client-side rather than via the server, counter to the architectural intent.

## other

- wt/wt/shared/configuration.py:69–75 — Fallback daemon socket path uses md5 and hardcoded "/tmp". This hash is not used for security (only for shortening a path); prefer a modern, non‑FIPS‑blocked hash (e.g., hashlib.blake2b(digest_size=6).hexdigest()[:12] or sha256) or use md5(..., usedforsecurity=False) where available; and use tempfile.gettempdir() instead of "/tmp". Consider adding per‑user scoping (e.g., os.getuid()) to avoid cross‑user collisions. Context: this path is a short AF_UNIX socket fallback when WT_DIR is too long on macOS; keep total path ≤ ~100 bytes.
- Design issue: WT_DIR can be silently ignored — the socket may be placed under /tmp with a hashed name when the path is long. This violates user expectations that WT_DIR is the anchor for all daemon files (configs/sockets/PIDs). Correct behavior: respect WT_DIR exactly; if the AF_UNIX path is too long, hard‑fail with a clear error. If a fallback must exist, make it explicit (opt‑in config/flag) and surface the final socket path prominently; do not rewrite silently.
  - Additionally, /tmp is not an appropriate location for long‑lived sockets/PID files; prefer within WT_DIR or an OS runtime dir (e.g., XDG_RUNTIME_DIR), not a global temp namespace.
  - Low‑priority if fallback retained: keep a small, readable slug from WT_DIR (sanitized suffix/prefix) alongside the hash for debuggability; and mark the hash call with usedforsecurity=False if md5 is kept (linter appeasement only).

- wt/wt/client/view_formatter.py:114, 179, 300 — Duplicate PR link construction; extract a helper and reuse:

```python
# view_formatter.py (nearby helper)
def pr_url(n: int) -> str:
    return f"http://go/pull/{n}"

# call sites
self.make_hyperlink(pr_url(pr_number), f"#{pr_number}")
```

- wt/wt/server/wt_server.py: 2582–2616 — __main__ block is too long; promote logic into a `main()` function (config load, logging setup, run loop) and keep the `if __name__ == "__main__":` block ≤ ~5 lines delegating to `main()`.

- wt/wt/server/wt_server.py: 2505–2514 — write_startup_handshake: represent the handshake as a shared Pydantic model (server+client), not a raw dict; serialize at the boundary only.
- wt/wt/server/wt_server.py: 640–679, 670–679, 1045–1076 — GitStatusdProcess mixes gitstatusd and GitHub concerns; split responsibilities (separate class/service) or rename to reflect broader scope.
- wt/wt/server/wt_server.py: 1023–1025 — Type consistency: `cache_age` is float or "never" (str). Use a real sentinel (None/Enum) and format at the boundary. Semantically, "never" is not an age — represent freshness as a timestamp and let the client compute deltas:

```python
# Better: return `cached_at` (datetime or epoch millis) or None; client formats age
cached_at: float | None = self.pr_last_fetched  # seconds since epoch or None
# UI/logging example
age_str = "never" if cached_at is None else f"{current_time - cached_at:.1f}s"
```

Observation: `cache_age` is only used for server-side logging (MISS/HIT messages), not piped to the client; switching to `cached_at` is backward‑compatible for logs and improves protocol semantics if later exposed. If it truly remains logging-only, a boolean `has_cached_pr_info` (or `fresh_cache`) is enough; keep timestamp if clients will compute deltas.

```python
# before
cache_age = ((current_time - self.pr_last_fetched) if self.pr_last_fetched else "never")

# after (Option 1: Optional[float])
age: float | None = (
    None if self.pr_last_fetched is None else current_time - self.pr_last_fetched
)
age_str = "never" if age is None else f"{age:.1f}s"

# after (Option 2: Enum sentinel)
class CacheAge(Enum):
    NEVER = "never"

age = CacheAge.NEVER if self.pr_last_fetched is None else current_time - self.pr_last_fetched
age_str = age.value if isinstance(age, CacheAge) else f"{age:.1f}s"
```
- wt/wt/server/wt_server.py: 1425–1430 — Redundant conditional block duplicated (same membership check twice); remove the duplicate branch.
- wt/wt/server/wt_server.py: 898–909 — `_update_comprehensive_cache` name is vague; prefer a precise name (e.g., `_update_status_cache`).
- wt/wt/server/wt_server.py: 666–671 — `cached_working_status: tuple[list[str], list[str]] | None` lacks semantics; introduce a descriptive dataclass or named alias capturing what each list represents.


- wt/wt/server/wt_server.py: 2359–2363 — Simplify if/else assignment to a guard-style assignment to remove the else branch:

```python
# before
if current_relative_path:
    current_dir = target_path / current_relative_path
else:
    current_dir = target_path

# after
current_dir = target_path
if current_relative_path:
    current_dir = current_dir / current_relative_path
```

- wt/wt/server/git_manager.py: `log_format` ignores its `format_str` parameter and the only caller (`wt/wt/server/worktree_service.py`:62) immediately parses the string back. Replace with a structured return (no format+parse roundtrip).
- wt/wt/server/wt_server.py (_run_post_creation_script_streaming):
  - Return shape includes `ran` (always True) and `error` (always None) — remove redundant fields and signal errors via exceptions; return a structured result object.
  - Output forwarding collects stdout/stderr as lines with repeated `.decode(errors="replace")` and rejoins. Prefer reading raw bytes and either returning byte buffers or decoding once at the boundary; avoid lossy line-based decoding unless the consumer requires line semantics.
- wt/wt/shared/protocol.py:29–31 — Prefer `str.removeprefix("wtid:")` over slicing (`wtid[5:]`) for fixed-prefix removal (mirrors our Python convention).
- wt/tests/integration/test_shell_integration.py: prefer simple assertions over `pytest.fail(...)`; use `assert len(parts) == 5, f"Bad output: {s}"` at 229; assert non-empty `output_lines` at 156–157; apply the same assert style at ~163–164.
- Replace PR-shaped dicts with typed models:
  - Client rendering uses dicts with keys like `number`, `mergeable`, `additions`, `deletions` (wt/wt/client/view_formatter.py:109–125, 178–202, 295–306). Prefer `PRData` (from `shared/github_models.py`) and build hyperlinks/status from its fields.
  - Server builds ad-hoc PR dicts (wt/wt/server/wt_server.py:627, 629–630; 1070, 1072–1073). Prefer `GitHubPRResponse` → `coerce_prdata()` to `PRData`, and pass `PRData` through to the client. This removes key-typo risks and keeps field names consistent.
  - wt/wt/server/wt_server.py: 997–1075 (`_get_github_pr_info`) returns a PR-shaped dict; return a structured model (e.g., `PRData`) instead and update callers. Apply the same to `PRService.get_pr_info` for consistency across server-side PR info access.

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
- wt/wt/server/wt_server.py: 2501–2502 — Avoid synchronous file I/O inside async functions; if a blocking write is kept, at least use the concise Path form (`self.pid_file.write_text(...)`). Prefer non-blocking designs (e.g., to_thread) when feasible. Applies to any simple `with open(..., "w") as f; f.write(...)` two-liner inside async code.

## Status snapshot shape consolidation
- wt/wt/server/wt_server.py: 898–909 (_update_comprehensive_cache) returns a tuple that mirrors StatusSnapshot; unify by returning StatusSnapshot from this path.
- wt/wt/server/wt_server.py: 750–796 (build_status_snapshot) should return a StatusSnapshot (compose internally) rather than a tuple; update consumers accordingly.
- wt/wt/server/wt_server.py: 798–802 (get_status) slices the tuple; prefer accessing fields on StatusSnapshot.

## kill_daemon_and_verify: further simplifications (not covered yet)
- wt/tests/conftest.py: 254–267 — Simplify the post-timeout verification: if `pid_file` still exists after deadline, fail immediately; avoid multi-branch relabeling.
- wt/tests/conftest.py: 258–265 — Shorten failure messages to concise one-liners; avoid verbose paragraphs in assertions.
- wt/tests/conftest.py: 192 — Remove the `timeout` parameter (use a constant or fixture-level setting); keep API minimal.
- wt/tests/conftest.py: 214–221 — Accept `wt_dir: Path` directly (domain: WT_DIR ≠ repo root); avoid recomputing from `repo_path`.
- Optional: verify PID changes across checks to detect daemon restarts during shutdown; unify process-existence and pid-file checks.

## Config construction surface-form rules (not covered yet)
- Prefer direct keyword arguments over dict merges like `**{**a, **b}` when both dicts are known at the callsite; improves readability and diffability.
- Prefer passing explicit kwargs to Pydantic models rather than assembling an intermediate kwargs dict when simple `a=b` is immediately available.
