- **wt/wt/server/gitstatusd_client.py**:
  - 338–355 — `_safe_get_repository_state` treats missing/invalid state as NORMAL.
    Do not mask errors as a valid state; raise or return an error.
  - `parse_gitstatusd_response` (L358), `create_gitstatusd_request` (L363) — thin wrappers around GitStatusdProtocol migrate any callers to Protocol methods and delete.

## [Try/except is scoped around the operation it guards](../../definitions/python/scoped-try-except.md)

- **wt/wt/server/wt_server.py**:
  - 2186–2240 — Path-within-worktrees check: scope try/except to only the relative_to(...) call and move follow-up logic outside;
    if not under main repo, early-bail with an error, otherwise return main immediately (overlaps with early-bailout)
    Before:
    ```python
    try:
        rel_path = absolute_path.relative_to(self.config.worktrees_dir)
        worktree_name = rel_path.parts[0] if rel_path.parts else None
        if len(rel_path.parts) > 1:
            relative_path = str(Path(*rel_path.parts[1:]))
        else:
            relative_path = ""
    except ValueError:
        # Path is not within worktrees directory - check if it's main repo
        ...
    ```
    After:
    ```python
    try:
        rel_path = absolute_path.relative_to(self.config.worktrees_dir)
    except ValueError:
        if not absolute_path.is_relative_to(self.config.main_repo):
            raise ValueError(f"Path {absolute_path} is not a managed worktree")
        worktree_name = MAIN_WORKTREE_DISPLAY_NAME
        relative_path = str(absolute_path.relative_to(self.config.main_repo))
        return self._create_success_response(...)
    # happy path (in worktrees dir)
    worktree_name = rel_path.parts[0] if rel_path.parts else None
    relative_path = "" if len(rel_path.parts) <= 1 else str(Path(*rel_path.parts[1:]))
    ```

## [No dead code](../../definitions/no-dead-code.md)

- **wt/wt/client/view_formatter.py**: dead code: `_get_sync_column` (L149), `render_worktree_processes`, `render_worktree_removal_progress`, `render_worktree_removal_git_status`
- **wt/tests/conftest.py**: 122–124 — `empty_worktree_status()` is unused; delete the fixture.
- **wt/wt/server/gitstatusd_client.py**:
  - dead code: `parse_gitstatusd_response` (L358), `create_gitstatusd_request` (L363) — thin wrappers around GitStatusdProtocol migrate any callers to Protocol methods and delete.

- **wt/wt/shared/constants.py**: 12 — `FILE_DISPLAY_LIMIT` is unreferenced.
  - Integrate: use as the default display cap in `wt/wt/client/view_formatter.py` (e.g., `format_list_with_more(..., max_items: int = FILE_DISPLAY_LIMIT)`).
  - Note: ViewFormatter currently defaults `max_items` to 3, while `FILE_DISPLAY_LIMIT` is 10 — decide desired UX and align (either set the constant to 3, or pass an explicit max where you want 3).
- **wt/wt/server/gitstatusd_client.py**:
  - dead code: `branch_status`; remove.
    GAP: Presentation/view concerns (branch display state) should not live in the core client.
  - 294–355 — After validating `len(fields) >= MIN_GIT_REPO_FIELDS` at the boundary, internal helper parsers should not catch `IndexError` or substitute defaults; these branches are unreachable and should be removed or replaced with hard guards.
    GAP: Clarify boundary vs helper responsibility for short‑array handling so index checks live in one place.
- **wt/wt/server/wt_server.py**:
  - 1425–1430 — Redundant conditional block duplicated (same membership check twice); remove the duplicate branch.
    GAP: Choose a consistent layer for conversion (e.g., relative→absolute) and apply it symmetrically across inputs; avoid split responsibility.
  - 1789–1844 — Unreachable code continues after a return; remove the dead block or revive it.
  - 1995–2001 — `if writer is None` branch is dead within handle_client_request path; remove dead branch and unify script execution handling.
    Rationale: `_handle_worktree_create_request(..., writer: asyncio.StreamWriter | None)` is only invoked from `handle_client_request(...)` (1472–1579) as `_handle_worktree_create_request(request, start_time, writer)` where `writer` is the non-None stream passed by asyncio. There are no call sites passing `None`, so the `writer is None` path is unreachable.
    GAP: Link this dead branch with the typing finding (make writer non‑optional) so the contract is explicit in the signature.

## [Pydantic 2 only](../../definitions/python/pydantic-2.md)

- **wt/wt/shared/github_models.py**: 73, 101, 217 — Uses v1-style class Config; switch to `model_config = ConfigDict(...)` (Pydantic v2).

## [Time and duration use rich time types](../../definitions/domain-types-and-units/time.md)

- **wt/wt/server/wt_server.py**:
  - 147–153 — `debounce_delay`, `periodic_interval` should be `datetime.timedelta` (not float seconds)
  - 1243–1251 — don't downgrade datetime type to numeric with total_seconds() for threshold compare; prefer a timedelta literal.
    Before:
    ```python
    if (
        self.daemon_health.last_error_time
        and (datetime.now() - self.daemon_health.last_error_time).total_seconds() > 60
    ):
        ...
    ```
    After:
    ```python
    if self.daemon_health.last_error_time and (
        datetime.now() - self.daemon_health.last_error_time
    ) > datetime.timedelta(minutes=1):
        ...
    ```
- **wt/tests/test_utils.py**: 6, 33 — `run_cli_command`, `run_cli_sh_command` use float durations; prefer `timedelta`

## [Modern type hints](../../definitions/python/type-hints.md)

- **wt/tests/integration/test_shell_integration.py**: 37 — `env: dict = None` uses a non-None default with a non-optional type; annotate as `dict[str, str] | None` (or build a dict where needed) and handle `None` explicitly
- **wt/wt/server/wt_server.py**:
  - 72 — parameter `error_message: str = None` should be annotated as `str | None` to match the default.
  - 424–428 — WorktreeRuntime uses quoted forward references ("GitstatusdClient", "PRService");
    use `from __future__ import annotations` reorder definitions, and annotate directly.

## [Use pytest's standard fixtures for temp dirs and monkeypatching](../../definitions/python/pytest-standard-fixtures.md)

- Test suite contains a hand-rolled cwd manager fixture duplicating standard pytest monkeypatch capabilities; use `monkeypatch.chdir(tmp_path)` and friends instead.
  - Hand-rolled cwd manager: `wt/tests/conftest.py`:153–169 (manual `os.chdir` context manager instead of `monkeypatch.chdir`)
  - Raw tempfile usage and manual cleanup: `wt/tests/e2e/test_path_watcher_integration.py`:18 (shared test helper)
  - `NamedTemporaryFile` for script creation (prefer `tmp_path`): `wt/tests/integration/test_shell_integration.py`:81

## [No one-off vars and trivial wrappers](../../definitions/no-oneoff-vars-and-trivial-wrappers.md)

- **wt/wt/server/git_manager.py**: `repo_root` is a trivial pass-through to `get_repo_root`; delete it and make callers call `get_repo_root` instead.
  - Only user: `wt/wt/server/worktree_service.py`:221
- **wt/tests/integration/test_shell_integration.py**:
  - L29 — `create_shell_script()` is used exactly once; inline at call site (in `run_wt_command`) instead of keeping a one-off helper
  - duplicate `daemon_cleanup` helper defined twice (one copy at 216–222); extract a single helper and reuse
- **wt/wt/server/wt_server.py**:
  - 1580–1582 — `_create_success_response` is a trivial pass-through; inline `Response(result=..., id=...)` at call sites.
  - ~2168–2169 — Inline one-off `result` variable.
    Before:
    ```python
    result = WorktreeListResult(worktrees=worktrees)
    return self._create_success_response(result, request.id)
    ```
    After:
    ```python
    return self._create_success_response(WorktreeListResult(worktrees=worktrees), request.id)
    ```
- **wt/wt/cli.py**: 137–143 — `all_args` is a one‑off; inline the combined args directly in the loop (e.g., `for arg in [*args, *ctx.args]: ...`).
- **wt/wt/plugins.py**:
  - 23–26 — Oneline the wt_init hookspec docstring: `"""Optional initialization hook; can modify config or set globals."""`
    Before:
    ```python
    def wt_commands(self) -> dict[str, Callable]:  # type: ignore[override]
        return {}
    def wt_init(self, config) -> None:  # type: ignore[override]
        return None
    ```
    After:
    ```python
    def wt_commands(self) -> dict[str, Callable] | None:
        return {}
    def wt_init(self, config) -> None:
        pass
  - 31, 35 — Align hook impl signatures with hookspecs; remove `# type: ignore[override]`, and prefer `pass` over `return None` when returning `None`.
  - 39–49 — `PluginIO` is a stateless thin wrapper over shell_utils; remove it, or refactor into a real interface (Protocol + concrete implementation) only if an IO boundary is needed.
  - 56–58 — Inline one-off variable in entry point iteration:
    Before:
    ```python
    eps = md.entry_points().select(group=ENTRYPOINT_GROUP)
    for ep in eps:
        ...
    ```
    After:
    ```python
    for ep in md.entry_points().select(group=ENTRYPOINT_GROUP):
        ...
    ```
  - 76–78 — `resolve_command(pm, name)` is a trivial wrapper; inline `get_plugin_commands(pm).get(name)` at the call site.
- **wt/wt/shared/constants.py**: 4–5 — Make COMMAND_NAMES the single source of truth and use it in the CLI routing; remove duplicated hardcoded lists in the CLI.
- **wt/wt/server/gitstatusd_client.py**: 204–205 — Inline one-off temp: `is_git_repository = int(fields[1]) == 1` (or `== "1"` if wire is str).
  Before:
  ```python
  is_git_repo_flag = int(fields[1])
  is_git_repository = is_git_repo_flag == 1
  ```
  After:
  ```python
  is_git_repository = int(fields[1]) == 1
  ```

## [Use pathlib for path manipulation](../../definitions/python/pathlib.md)
- **wt/wt/shared/configuration.py**: fold file/read/parse/validate into concise pathlib oneliner
  Before:
  ```python
  with open(config_path) as f:
      data = yaml.safe_load(f)
  try:
      config_file = ConfigFile(**data)
  except ValidationError as e:
      raise ConfigError(f"Configuration validation errors: {e}")
  ```
  After:
  ```python
  try:
      config_file = ConfigFile.model_validate(yaml.safe_load(config_path.read_text()))
  except ValidationError as e:
      raise ConfigError(f"Configuration validation errors: {e}")
  ```
- **wt/wt/server/wt_server.py**:
  - 414–416 — StatusSnapshot.dirty_files/untracked_files are filesystem paths; use `list[Path]` over `list[str]`.
    GAP: Clarify wire vs internal types; document conversion boundaries to avoid mixed types across layers.
  - 2369–2382 — `_compute_teleport_target` returns `str`; return `Path` (preferred) and avoid downstream `str(...)` conversions.
    GAP: Commit to a single type/contract across layers; avoid mixed str/Path states; specify where conversion happens.
  - 2501–2502 — In async context, if kept as a synchronous write, prefer the one-liner Path I/O form: `self.pid_file.write_text(str(os.getpid()))`. Applies to any simple two-line "with open(..., 'w') as f; f.write(...)" pattern where `Path.write_text(...)` suffices.
    GAP: Provide guidance for blocking I/O in async contexts (when allowed, preferred non-blocking patterns) and document exceptions.

## [No useless documentation or comments](../../definitions/no-useless-docs.md)

- **wt/wt/server/wt_server.py**:
  - 147–167 — DebouncedGitHubRefresh.__init__: replace inline “Configurable timing”/“State tracking” comments and trailing parameter comment with a proper Args docstring; remove redundant inline comments.
- **wt/wt/server/gitstatusd_client.py**:
  - properties `has_untracked_files` / `has_dirty_files` — Docstrings restate the obvious; remove

    TODO: SEPARATE NON-DOCUMENTATION / gap: Collapse to truthy one‑liners:
    ```python
    @property
    def has_untracked_files(self) -> bool:
        return bool(self.is_git_repository and self.untracked_files)
  
    @property
    def has_dirty_files(self) -> bool:
        return bool(self.is_git_repository and (self.staged_changes or self.unstaged_changes))
    ```
    GAP: Leverage truthiness where readable (re. original code `(x or 0) > 0`)

## [No unnecessary line breaks](../../definitions/no-extra-linebreaks.md)
- **wt/tests/conftest.py**: 298–300 — Collapse multi-line assert into one line: `assert shutil.which("gitstatusd"), "integration tests require gitstatusd on PATH"`.
- **wt/wt/server/wt_server.py**:
  - 1926–1930 — One-line function signature for `_handle_ping_request`; no need to split parameters across lines when short.
  - 1896–1898 — One-line initialization: `github=ComponentStatus(state=github_state),` (no unnecessary line breaks).
- **wt/wt/plugins.py**: 24–26 — One-line wt_init hookspec docstring: `"""Optional initialization hook; can modify config or set globals."""`.

## [Uses str.removeprefix / str.removesuffix for fixed prefix/suffix removal](../../definitions/python/str-affixes.md)

- **wt/wt/shared/protocol.py**: 29–31 — Use `str.removeprefix("wtid:")`, not (`wtid[5:]`)

## [Early bailout (guard clauses and loop guards)](../../definitions/early-bailout.md)

- **wt/wt/server/wt_server.py**:
  - 2149–2156 — In `worktree_list`, replace nested block with a guard `continue` to reduce nesting.
  - ~1648 — In `process_single_worktree`, invert the guard to early‑bail when `gs_client` is missing and keep the happy path flat. Consider extracting the if/else into a helper to enable clean return‑then‑massage flow.
    Before (shape):
    ```python
    if gs_client:
        ...  # big branch
    else:
        ...  # small branch
    ```
    After (refactor sketch):
    ```python
    from pathlib import Path
    from datetime import datetime
  
    def _compute_single_status(worktree_path: Path, gs_client) -> WorktreeGitStatus:
        if not gs_client:
            return WorktreeGitStatus(
                state="stopped",
                dirty_files=[],
                untracked_files=[],
                ...,
            )
        # happy path (cache, bounded refresh, meta + PR fetch)
        ...
  
    # in process_single_worktree
    single_start = time.time()
    gs_client = self.gitstatusd_clients.get(worktree_path)
    status = _compute_single_status(worktree_path, gs_client)
    individual_times[worktree_path] = (time.time() - single_start) * 1000
    return status
    ```
  - `_handle_worktree_identify_request` — invert `if worktree_name and absolute_path.exists()` to a negative guard and early return
    to keep the happy path flat.
    Before: `if worktree_name and absolute_path.exists(): ...`
    After: `if not worktree_name or not absolute_path.exists(): return ...  # early bailout`

## [No unnecessary nesting (combine trivial guards)](../../definitions/minimize-nesting.md)

- **wt/wt/cli.py**: 143 — Core can be made shorter while not hurting readability with a single pre-check and a comprehension.
  Before:
  ```python
  for arg in all_args:
      if arg in {"--help", "-h"}:
          show_help()
          return
      if arg in ["-c", "--force"]:
          filtered_args.append(arg)
      elif arg.startswith("-"):
          continue
      else:
          filtered_args.append(arg)
  ```
  After:
  ```python
  if {"--help", "-h"} & set(all_args):  # or: '--help' in ... or '-h' in ...
      show_help(); return
  filtered_args = [
      arg for arg in all_args
      if not arg.startswith("-") or arg in ("-c", "--force")
  ]
  ```
  GAP: Prefer comprehensions for simple filter/map over loops with append/continue when it fits on one readable line.
  Note: This matches “No unnecessary nesting” by collapsing trivial guard conditions into a single predicate before collection.
