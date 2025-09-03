## Dirty-state copy is never triggered

- Client only sends `source_branch`, so the daemon passes `None`; as a result, a dirty-state copy never happens.

## RPC surface: worktree identity contract

- `source_worktree` on the RPC violates the implicit contract that worktrees are identified by WorktreeID (opaque), not by alternative identifiers.

## Teleport resolution on client instead of server

- Client performs teleport resolution client-side rather than via the server, counter to the architectural intent.

## other

- shell_utils.controlled_error signature — commands param should not require a runtime None-check here.
  Options:
  - (a) Make commands non-None (e.g., default to empty list) and remove the `if commands:` branch.
  - (b) Remove commands parameter entirely; only usage with commands is in demo plugin (wt/wt/demo_plugin.py), and core callers don’t rely on it.

- PullRequestCache truthiness check in get_or_refresh — prefer concise Optional truthiness over `is None` when the type is `PullRequestCache | None` (no other falsy variants).
  Before:
  ```python
  cache = cls.load(cache_file)
  if cache is None or cache.should_invalidate(cache_expiration):
      ...
  ```
  After:
  ```python
  cache = cls.load(cache_file)
  if not cache or cache.should_invalidate(cache_expiration):
      ...
  ```

- Plugin API return value semantics are undocumented
  - wt/wt/plugins.py:15–20 — Hookspec allows run(...)-> int | None but doesn’t define what the int means. Document the contract (e.g., process exit status 0=success, non‑zero=error), specify how None is treated, and ensure the CLI caller interprets return codes consistently.
- Demo plugin quality (nit)
  - wt/wt/demo_plugin.py:10 — `wt_init` should use `pass`, not `return None`.
  - wt/wt/demo_plugin.py:22–24 — Inline `len(resp.results)` in the f-string: `print(f"demo: {len(resp.results)} worktrees")`.
- Redundant path checks in configuration
- Enum at the source
  - wt/wt/shared/configuration.py:163 — Convert `cow_method` to `CowMethod` at parse/validation time in ConfigFile (the source), not at Configuration construction. Keep enums typed at the source to avoid string churn and repeated conversions.
- PR mergeability enum is incomplete / unclear with None
  - wt/wt/shared/github_models.py:60–71 — `PRMergeability` omits “mergeable”/“clean” state and pairs with None in models, causing ambiguous None vs UNKNOWN semantics. Define a complete, explicit enum (e.g., MERGEABLE | CONFLICTING | UNKNOWN), and avoid combining with None unless documenting precise semantics.
- Consolidate overlapping PR models (reduce nullable sprawl)
  - Multiple overlapping representations exist (e.g., PRInfoRepr, GitHubPRResponse, PRData, PullRequest, PullRequestView) with ~80% field overlap and many nullable fields. Collapse to a single canonical PR model for server↔client, with clear field semantics and minimal nullability (only where truly optional). Provide adapters at boundaries (GitHub API → PR model; wire → PR model) and remove ad‑hoc coercions.
  - Heuristic: the current shapes do not faithfully model the domain (e.g., enums missing valid states, pervasive Optionals). The model should make invalid states unrepresentable; if a state can occur (e.g., “mergeable”), it must be represented explicitly, not via None/UNKNOWN ambiguity.
  - PRStatus ergonomics: drop `display_text` by using human‑friendly enum values (e.g., MERGED, CLOSED, MERGEABLE, CONFLICTING, OPEN) and rely on `.value`; avoid bespoke mapping methods for spacing/casing.
  - PRStatus.is_open should not rely on string prefixes (`name.startswith("OPEN_")`); define explicit states/membership (e.g., `self in {PRStatus.MERGEABLE, PRStatus.CONFLICTING, PRStatus.OPEN}`) or model openness orthogonally.

- CLI arg validation (no silent extra args)
  - wt/wt/cli.py: 232–236 — "-c" currently accepts any number of extra args but only uses the first; require exactly 1 arg (error if len(remaining_args) != 1).
  - wt/wt/cli.py: 238–241 — "path" command ignores extra args beyond two; enforce ≤2 args (error if len(remaining_args) > 2).
  - wt/wt/cli.py: 243–247 — "status" command ignores extra args; require ≤1 arg (error if len(remaining_args) > 1).
  - Suggestion: print a concise usage line via click.echo(...) and ctx.exit(1) when too many args are provided, mirroring the existing "cp" arity checks.

- Click usage errors (stderr, exit codes, idioms)
  - wt/wt/cli.py: For arity/usage errors (-c/path/status), prefer `ctx.fail("message")` (prints to stderr, exits with code 2) or raise `click.UsageError("message", ctx=ctx)`. If emitting manually, use `click.echo(..., err=True)` and `ctx.exit(2)`. Idiomatic: exit code 2 for usage errors, 1 for generic exceptions (`click.ClickException`). Where possible, declare arguments with Click (nargs/required) so Click handles arity automatically.

- CLI help/table formatting
  - wt/wt/cli.py: 32–41 (FLAGS) and 72–76 (EXAMPLES) — Use tabulate to render tables instead of manual padding with f-strings.
    Example:
    ```python
    from tabulate import tabulate
    click.echo("FLAGS:")
    click.echo(tabulate(flags, tablefmt="plain"))
    click.echo("\nEXAMPLES:")
    click.echo(tabulate(examples, tablefmt="plain"))
    ```
- Lazy gitstatusd start at handler layer
  - wt/wt/server/wt_server.py: ~1628 — get_status handler triggers gitstatusd start when missing. Extract a boundary/service that encapsulates "ensure running + get cached or compute" so the handler stays a thin RPC boundary.
- Duplicate exception fallback for commit/ahead/branch: bundle into struct
  - wt/wt/server/wt_server.py: ~1680 — try/except sets commit_info_data=None, ahead_behind=(0, 0), branch_name="HEAD", worktree_last_error=f"meta: {e}". If these fields are either-all-present or all-error, introduce a small dataclass (e.g., StatusBasics) with these fields and a factory `StatusBasics.from_exception(e)` and reuse instead of duplicating the assignment block.
- Use enum directly, avoid string→enum hop
  - wt/wt/server/wt_server.py: nearby — the function builds state as a str then converts to an Enum; prefer producing the Enum at source (e.g., PRState/DaemonHealthStatus) and only stringify at the boundary.
- List comprehension for worktree paths
  - wt/wt/server/wt_server.py: 1610–1614 — Replace for+append with list comprehension: `[self.config.worktrees_dir / parse_worktree_id(w) for w in worktree_ids]`.
- Unify script execution branch (null writer)
  - wt/wt/server/wt_server.py: 1995–2008 — Unify the “no writer” and streaming writer paths: treat writer=None as a special case in the same code path (null object or optional writer) instead of a parallel implementation.
  - Related dead code: The `writer is None` branch is unreachable on the only call path (handle_client_request always provides a non-None StreamWriter). Link: see covered.md “No dead code” at wt_server.py:1995–2001 with rationale.
  - Invocation: the “no writer” branch calls WorktreeService.execute_post_creation_script(str(script), worktree_path) — if retained, prefer Path arguments to match property PathLike and avoid redundant str conversions.
  - Caller check: WorktreeService.execute_post_creation_script is still called from worktree_service.py:157 (live path). Therefore the function itself is not dead; only the wt_server.py call site is dead.
  - Type contract: Mark `_handle_worktree_create_request(..., writer)` as non‑nullable in the signature (writer: asyncio.StreamWriter); current Optional type suggests a path that cannot occur on the only call site.
  - Use typed model, not raw dict: `post` is later passed into `HookRunResult(**post)`; construct a `HookRunResult` (or None) directly rather than assembling a dict.
  - Call stack (live path): CLI → client handler → server request handler → script exec
    - wt/wt/cli.py (“-c” branch) → wt/wt/client/handlers.py: handle_create_worktree → JSON‑RPC method "worktree_create"
    - Server: wt/wt/server/wt_server.py: handle_client_request(...) → _handle_worktree_create_request(request, start_time, writer) → _run_post_creation_script_streaming(..., writer)
    - Conclusion: execution is server‑side; not the earlier “client does server work” finding. If we later move script execution elsewhere, the dead branch would be removed entirely.
- Simplify readiness summing expression
  - wt/wt/server/wt_server.py: 1867 — Replace generator + predicate with int-cast for brevity when readable.
    Before:
    ```python
    with_git = sum(1 for p in self.gitstatusd_clients.values() if p.is_running)
    ```
    After:
    ```python
    with_git = sum(p.is_running for p in self.gitstatusd_clients.values())  # bools sum to ints
    ```
- Avoid needless dict copy
  - wt/wt/server/wt_server.py: 1907–1915 — Replace comprehension copy with direct pass-through when no transformation is applied.
    Before:
    ```python
    status_response = StatusResponse(
        results={k: v for k, v in results.items()},
        ...
    )
    ```
    After:
    ```python
    status_response = StatusResponse(
        results=results,
        ...
    )
    ```
- DRY WorktreeID/name computation
  - wt/wt/server/wt_server.py: duplicate logic for (wtid, resolved_name) based on `is_main` appears in:
    - _handle_worktree_get_by_name_request: 296–302
    - _handle_worktree_identify_request: 256–262
  - Extract a helper (e.g., `def compute_id_and_name(info) -> tuple[str, str]: ...`) and reuse.
- Duplicate post-creation script validation (per-exec double-check unnecessary)
  - wt/wt/server/wt_server.py: 1971–1977 and ~2474–2511 — two validations exist. The per-execution “double-check” is paranoid without a plausible race; drop it and keep a single authoritative check (e.g., at startup).
  Before:
  ```python
  # Double-check just before execution in case it disappeared since pre-check
  script = self.config.post_creation_script
  if not script.exists() or not script.is_file():
      raise FileNotFoundError(
          f"Post-creation script not found at execution time: {script}",
      )
  ```
  If retained, shorten:
  ```python
  if (script := self.config.post_creation_script) and not script.is_file():
      raise FileNotFoundError(f"Post-creation script is not a file: {script}")
  ```

- Centralize handler error logging (fold try/except log+re-raise)
  - wt/wt/server/wt_server.py: multiple handlers wrap bodies in `try: ... except Exception: logger...; raise`. Prefer a shared boundary that logs with handler/method name; remove per-handler boilerplate strings (e.g., "Error listing worktrees").
- Concurrent shutdown of gitstatusd processes
  - wt/wt/server/wt_server.py: 571–573 — Stop all processes concurrently with `asyncio.gather`.
    Before:
    ```python
    # Stop all gitstatusd processes
    for process in list(self.gitstatusd_clients.values()):
        await process.stop()
    ```
    After:
    ```python
    await asyncio.gather(*(p.stop() for p in self.gitstatusd_clients.values()))
    ```
- Merge duplicated filesystem event handlers
  - wt/wt/server/wt_server.py: 360–380 — GitFileHandler.on_modified and on_created have identical bodies; extract a shared helper (e.g., `_handle_fs_event(event)`) and call it from both, or register a single callable (functools.partial) if a distinguisher is desired. Avoid duplicating full bodies just to distinguish "created" vs "modified".
- Promote static config to constant
  - wt/wt/server/wt_server.py: 349–358 — `self.watched_patterns` is a static set of strings; promote to a class-level or module-level constant (e.g., WATCHED_GIT_PATTERNS: tuple[str, ...] | frozenset[str]) instead of per-instance mutable state.

- Logging ergonomics (f"{var=}")
  - wt/wt/server/gitstatusd_client.py:212 — Prefer f"{request_id=}" over legacy %s formatting; adopt f-string name=value form for similar debug messages across the codebase.

- Consistency: avoid mixing git subprocess calls with library-backed GitManager
  - wt/wt/server/wt_server.py: 305–340 — `_fetch_origin_master` shells out via `asyncio.create_subprocess_exec("git", "fetch", "origin", "master")` while other code uses GitManager/libgit2. Prefer a single backend (e.g., call through GitManager or pygit2/GitPython), or centralize subprocess usage behind a thin adapter to keep behavior uniform and testable.
  - Additionally, when subprocess is necessary, use the shared wrapper in `wt/wt/shared/git_utils.py` (disables hooks via `-c core.hooksPath=`) to ensure consistent behavior (no surprise hooks). This helper is currently not used here — inconsistency.
- Mixing concerns in DebouncedGitHubRefresh._do_refresh
  - wt/wt/server/wt_server.py: 279–301 — `_do_refresh` performs both a `git fetch origin/master` and a GitHub PR refresh in one method. Split responsibilities (e.g., `_fetch_origin` and `_refresh_github_data`) or make the fetch explicit/opt‑in (config flag/parameter). As an API user, calling “GitHub refresh” should not implicitly trigger a git fetch unless documented and deliberately designed; at minimum, rename to reflect behavior if coupled by design.
- Conciseness: prefer free helper functions over verbose staticmethod access
  - wt/wt/server/gitstatusd_client.py — Repeated calls like `GitStatusdProtocol._safe_get_int(fields, idx)` are noisy in object construction blocks (e.g., index_file_count, staged_changes, unstaged_changes, conflicted_changes, untracked_files, commits_ahead_upstream, commits_behind_upstream). Consider module-level helpers (e.g., `_get_int`, `_get_str`) for succinct field extraction.
    Before:
    ```python
    index_file_count=GitStatusdProtocol._safe_get_int(fields, 9)
    staged_changes=GitStatusdProtocol._safe_get_int(fields, 10)
    ...
    commits_behind_upstream=GitStatusdProtocol._safe_get_int(fields, 15)
    ```
    After:
    ```python
    index_file_count=_get_int(fields, 9)
    staged_changes=_get_int(fields, 10)
    unstaged_changes=_get_int(fields, 11)
    conflicted_changes=_get_int(fields, 12)
    untracked_files=_get_int(fields, 13)
    commits_ahead_upstream=_get_int(fields, 14)
    commits_behind_upstream=_get_int(fields, 15)
    ```
- Minor simplification in to_wire_format
  - wt/wt/server/gitstatusd_client.py:52 — Replace '"1" if disable_index_computation else "0"' with `int(self.disable_index_computation)` or `{self.disable_index_computation:d}` in the f-string.
- Response shape for gitstatusd: payload vs None
  - wt/wt/server/gitstatusd_client.py: 215–240 — When `is_git_repository` is False, do not include git payload fields on the response. Prefer an explicit shape: either `gitstatusd=None` (not a git repo), or `gitstatusd=GitStatusPayload(...)` where fields are non-nullable except where truly optional per protocol. This avoids half-populated objects and makes callers’ handling explicit.
- Protocol symmetry for wire format (consistency/low description complexity)
  - wt/wt/server/gitstatusd_client.py: Requests expose `to_wire_format` on GitStatusdRequest; responses are parsed via `GitStatusdProtocol.parse_response(...)`. Provide a symmetric `from_wire_format` (either as `GitStatusdResponse.from_wire_format(...)` or in the same Protocol facet) to keep the API consistent and easy to reason about (printable, mirrored surface).

- Remove misleading legacy shim
  - wt/wt/server/gitstatusd_client.py:373 `gitstatusd_response_to_legacy_format(...)` is a compatibility shim that fabricates placeholder strings (e.g., "<staged/unstaged files present>") instead of actual paths. This misleads callers (e.g., wt_server cached_working_status) and breaks users expecting real file lists. Remove the shim and update callers to use the real response fields.
  Before:
  ```python
  if not response.is_git_repository:
      return [], []
  dirty_files = []
  if response.has_dirty_files:
      dirty_files.append("<staged/unstaged files present>")
  untracked_files = []
  if response.has_untracked_files:
      untracked_files.append("<untracked files present>")
  return dirty_files, untracked_files
  ```
  After (direction):
  - Return the structured GitStatusdResponse throughout; render summaries at the view layer.
  - Where lists are required, add real filenames (or explicitly signal "counts only"), never placeholders.
  - Note: This shim is actively misleading — it puts non‑filenames into filename slots and pollutes all downstream consumers; remove ASAP.

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
- wt/tests/integration/test_shell_integration.py: prefer simple assertions over `pytest.fail(...)`; use `assert len(parts) == 5, f"Bad output: {s}"` at 229; assert non-empty `output_lines` at 156–157; apply the same assert style at ~163–164.
- Replace PR-shaped dicts with typed models (and remove ad-hoc coercions):
  - Client rendering uses dicts with keys like `number`, `mergeable`, `additions`, `deletions` (wt/wt/client/view_formatter.py:109–125, 178–202, 295–306). Prefer `PRData` (from `shared/github_models.py`) and build hyperlinks/status from its fields.
  - Server builds ad-hoc PR dicts (wt/wt/server/wt_server.py:627, 629–630; 1070, 1072–1073). Prefer `GitHubPRResponse` → `PRData` with a proper constructor/adapter at the boundary; eliminate ad‑hoc `coerce_prdata(src: Any)` and declare precise unions where a function truly accepts multiple concrete types.
  - wt/wt/server/wt_server.py: 997–1075 (`_get_github_pr_info`) returns a PR-shaped dict; return a structured model (e.g., `PRData`) instead and update callers. Apply the same to `PRService.get_pr_info` for consistency across server-side PR info access.
  - Principle: avoid “magic Any” coercers; call sites should know the real type. If multiple input types must be supported, accept a Union and provide explicit from_X constructors.
- Fold PR cache update logs
  - wt/wt/server/wt_server.py: 1104–1116 — Collapse the two logger.info branches into one, logging the PR number as None when absent (or using a single ternary in the format).
  - Rationale: Friendly, branched messages ("no PR" vs "PR #1234") cost ~6–10 lines and a conditional. That’s worth it in user‑facing output, but for developer logs the compact form (e.g., pr=1234 or pr=None) is sufficiently readable and avoids repetition. Prefer brevity here; use the friendlier form only where end‑users see it.

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

## Status snapshot shape and naming
- wt/wt/server/wt_server.py: 1695–1697 — Cache flags `is_cached` vs `is_stale` are confusing; clarify semantics and naming. If you keep booleans, make them self‑documenting (e.g., `has_worktree_cache`, `is_cache_older_than_refresh_age`) and document the distinction where they’re set and consumed.
- wt/wt/server/wt_server.py: 898–909 (_update_comprehensive_cache) returns a tuple that mirrors StatusSnapshot; unify by returning StatusSnapshot from this path.
- wt/wt/server/wt_server.py: 750–796 (build_status_snapshot) should return a StatusSnapshot (compose internally) rather than a tuple; update consumers accordingly.
- wt/wt/server/wt_server.py: 798–802 (get_status) slices the tuple; prefer accessing fields on StatusSnapshot.
- Naming: remove/rename the weasel word “comprehensive” in names/logs/docstrings; prefer precise names (e.g., `_update_status_cache`) and log text (“Returning cached status …”).

## kill_daemon_and_verify: further simplifications (not covered yet)
- wt/tests/conftest.py: 254–267 — Simplify the post-timeout verification: if `pid_file` still exists after deadline, fail immediately; avoid multi-branch relabeling.
- wt/tests/conftest.py: 258–265 — Shorten failure messages to concise one-liners; avoid verbose paragraphs in assertions.
- wt/tests/conftest.py: 192 — Remove the `timeout` parameter (use a constant or fixture-level setting); keep API minimal.
- wt/tests/conftest.py: 214–221 — Accept `wt_dir: Path` directly (domain: WT_DIR ≠ repo root); avoid recomputing from `repo_path`.
- Optional: verify PID changes across checks to detect daemon restarts during shutdown; unify process-existence and pid-file checks.

## Config construction surface-form rules (not covered yet)
- Prefer direct keyword arguments over dict merges like `**{**a, **b}` when both dicts are known at the callsite; improves readability and diffability.
- Prefer passing explicit kwargs to Pydantic models rather than assembling an intermediate kwargs dict when simple `a=b` is immediately available.
