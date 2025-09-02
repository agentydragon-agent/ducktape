## [Imports at the top](../../definitions/python/imports-top.md)

Many inline imports appear inside functions across modules in `wt/`; imports should live at module top unless a narrowly justified exception applies (cycle break, heavy import deferral, plugin/hot-reload).

- **wt/wt/cli.py**: 101, 158, 193, 198, 206, 253
- **wt/wt/client/handlers.py**: 10, 16, 50, 75, 86, 89, 94, 97, 104, 120, 127, 134, 136, 142, 152, 164–168, 194, 196, 201, 214, 220, 226, 238, 240, 242–243, 249, 254, 263, 277, 298, 301–302, 310, 342
- **wt/wt/client/shell_utils.py**: 9, 16
- **wt/wt/client/worktree_utils.py**: 83, 108–109, 148
- **wt/wt/client/wt_client.py**: 42, 67, 99, 168
- **wt/wt/server/github_client.py**: 109
- **wt/wt/server/copy_strategies.py**: 123, 139
- **wt/wt/plugins.py**: 41, 46
- **wt/wt/server/worktree_service.py**: 105, 197, 214, 264, 281, 293, 300–301, 388, 445, 490, 507, 513
- **wt/wt/server/wt_server.py**: 85, 102, 1149, 1171, 1186, 1217, 1240, 1608, 1736, 1741, 1815, 1864, 1884–1888, 1996, 2021, 2103, 2117, 2155, 2583–2587
- **wt/wt/shared/configuration.py**: 69
- **wt/wt/shared/error_handling.py**: 141
- **wt/tests/e2e/test_path_watcher_integration.py**: 23, 60
- **wt/tests/integration/test_shell_integration.py**: 41, 42, 57, 63, 64, 66
- **wt/tests/test_utils.py**: 10, 15
- **wt/tests/repo_factory.py**: 165

## [Use StrEnum for string‑valued enums](../../definitions/python/strenum.md)

- **wt/wt/shared/github_models.py**: 13–18, 49–52, 60–62
- **wt/wt/shared/configuration.py**: 21–27
- **wt/wt/shared/protocol.py**: DaemonHealthStatus (34–40), StartupPhase (317–322), ComponentState (435–441), GitstatusdState (443–449)
- **wt/wt/server/gitstatusd_client.py**: RepositoryState (29–43)
- **wt/wt/server/copy_strategies.py**: StrategyType (18–23)

## [Markdown inline formatting for code identifiers, flags, paths, and URIs](../../definitions/markdown/inline-formatting.md)

- **wt/ARCHITECTURE.md**: 256, 259 have plain "WT_DIR" references
- **wt/WORKTREE_IDEAS.md**: 7, 16 have plain "WT_DIR" references
- **wt/README.md**: 16, 18, 190 have plain "PATH" / env var references
- **wt/tests/README.md**: 68, 71 — bare WT_DIR; wrap in code spans

## [Pass Path objects to PathLike APIs (no str())](../../definitions/python/pathlike.md)

- **wt/wt/server/copy_strategies.py**:
  - Basic: 46, 63, 111
  - Also `_get_copyable_entries` casts `Path` to `str` while it's used for the purpose of passing into `subprocess.run`; should just return unconverted `Path`
- **wt/wt/server/worktree_service.py**: 337
- **wt/wt/shared/git_utils.py**: 29
- **wt/wt/server/wt_server.py**: 2052
- **wt/tests/repo_factory.py**: 172, 188

## [Try/except is scoped around the operation it guards](../../definitions/python/scoped-try-except.md)

- **wt/wt/server/wt_server.py**: ~2074 — `except Exception: pass` silently swallows errors while streaming hook output; log the error and catch specific expected exceptions (or handle at a proper boundary).

## [Forbid dynamic attribute access and catching AttributeError](../../definitions/python/forbid-dynamic-attrs.md) 

- `getattr(pygit2, "GIT_STATUS_...", 0)` should be plain `pygit2.GIT_STATUS_...` (see property link above)
  - **wt/wt/server/git_manager.py**: 116–123.
  - **wt/wt/server/worktree_service.py**: 143
- **wt/tests/config_factory.py**: 45–46 — pass presets by value (`ConfigPresets.FOO`) instead of by name and `getattr`
  - 128: this also uses dynamic attribute access, but the deeper issue is the name-based pattern itself is brittle. With value-based presets, this code path is unnecessary—no name lookup or error-name formatting needed; prefer value-based API and delete this path.

## [Use PathLike for path parameters](../../definitions/python/pathlike.md)

- Functions should accept `Path`/`PathLike` rather than `str` for filesystem paths.
  - **wt/wt/server/git_manager.py**: 259 (worktree_add `path: str`), 297 (worktree_remove `path: str`)
  - **wt/tests/integration/test_shell_integration.py**: 34, 37 — `run_shell_script` should take `cwd: Path` (not `str`)
  - **wt/wt/client/wt_client.py**: 586 — `absolute_path: str` should be `Path`
  - **wt/wt/server/worktree_service.py**: 299 — `script_path: str` should be `Path`
  - **wt/wt/server/wt_server.py**: 227 — `file_path: str | None` should be `Path | None`
  - **wt/wt/server/wt_server.py**: 381 — `file_path: str` should be `Path`

## [No dead code](../../definitions/no-dead-code.md)

- logging_config.py: OperationLogger is dead code; JSONFormatter becomes unused once it’s removed.
- Duplicate hydration/post-creation script invocation paths: a duplicate implementation exists that’s only used by tests; production path is separate and not covered. Consolidate on the prod path.
- **wt/wt/server/git_manager.py**: dead code: `get_status_porcelain`, `status_porcelain`, `rev_count()`; `CannotDeleteWorktree` (L40)
- **wt/wt/server/gitstatusd_client.py**: dead code: `parse_gitstatusd_response` (L358), `create_gitstatusd_request` (L363)
- **wt/wt/server/wt_server.py**: dead code: `StatusSnapshot` (L413), `WorktreeRuntime` (L425), `GitStatusdProcess` (L640)
- **wt/wt/server/github_client.py**: dead code: `DisabledGitHubInterface` (L18)
- **wt/wt/shared/models.py**: dead code: `WorktreeParseState.finalize(...)` (L145)
- **wt/wt/shared/constants.py**: 12 — `FILE_DISPLAY_LIMIT` is unreferenced.
  - Integrate: use as the default display cap in `wt/wt/client/view_formatter.py` (e.g., `format_list_with_more(..., max_items: int = FILE_DISPLAY_LIMIT)`).
  - Note: ViewFormatter currently defaults `max_items` to 3, while `FILE_DISPLAY_LIMIT` is 10 — decide desired UX and align (either set the constant to 3, or pass an explicit max where you want 3).
- **wt/wt/shared/error_handling.py**: dead code: `WorktreeNotFoundError` (L23), `WorktreeAlreadyExistsError` (L27), `ProcessCheckError` (L31), `handle_git_errors` (L43), `handle_process_errors` (L76), `convert_to_click_exception` (L102), `safe_execute` (L120)
- **wt/wt/shared/github_models.py**: dead code: `PullRequest` (L65), `PullRequestView` (L92), `PullRequestCache`
- **wt/wt/shared/protocol.py**: dead code: `ProgressUpdate` (L426), `SUPPORTED_METHODS` (L497)
- **wt/wt/client/view_formatter.py**: dead code: `_get_sync_column` (L149), `render_worktree_processes`, `render_worktree_removal_progress`, `render_worktree_removal_git_status`

## [Pydantic 2 only](../../definitions/python/pydantic-2.md)

- **wt/wt/shared/github_models.py**: 73, 101, 217 — Uses v1-style class Config; switch to `model_config = ConfigDict(...)` (Pydantic v2).

## [Time and duration use rich time types](../../definitions/domain-types-and-units/time.md)

- **wt/wt/server/wt_server.py**: 147–153 — `debounce_delay`, `periodic_interval` should be `datetime.timedelta` (not float seconds)
- **wt/tests/test_utils.py**: 6, 33 — `run_cli_command`, `run_cli_sh_command` use float durations; prefer `timedelta`

## [Modern type hints](../../definitions/python/type-hints.md)

- **wt/tests/integration/test_shell_integration.py**: 37 — `env: dict = None` uses a non-None default with a non-optional type; annotate as `dict[str, str] | None` (or build a dict where needed) and handle `None` explicitly

## [Use pytest's standard fixtures for temp dirs and monkeypatching](../../definitions/python/pytest-standard-fixtures.md)

- Test suite contains a hand-rolled cwd manager fixture duplicating standard pytest monkeypatch capabilities; use `monkeypatch.chdir(tmp_path)` and friends instead.
  - Hand-rolled cwd manager: `wt/tests/conftest.py`:153–169 (manual `os.chdir` context manager instead of `monkeypatch.chdir`)
  - Raw tempfile usage and manual cleanup: `wt/tests/e2e/test_path_watcher_integration.py`:18 (shared test helper)
  - `NamedTemporaryFile` for script creation (prefer `tmp_path`): `wt/tests/integration/test_shell_integration.py`:81

## [No one-off vars and trivial wrappers](../../definitions/no-oneoff-vars-and-trivial-wrappers.md)

- **wt/wt/server/git_manager.py**: `repo_root` is a trivial pass-through to `get_repo_root`; delete it and make callers call `get_repo_root` instead.
  - Only user: `wt/wt/server/worktree_service.py`:221
- **wt/tests/integration/test_shell_integration.py**: 29 — `create_shell_script()` is used exactly once; inline at call site (in `run_wt_command`) instead of keeping a one-off helper
- **wt/tests/integration/test_shell_integration.py**: duplicate `daemon_cleanup` helper defined twice (one copy at 216–222); extract a single helper and reuse



## [Use pathlib for path manipulation](../../definitions/python/pathlib.md)
- **wt/tests/conftest.py**: 420–421 — Use Path one-liner: `config_path.write_text(yaml.dumps(config_file.model_dump()))` (small file).
- **wt/wt/server/wt_server.py**: 2501–2502 — In async context, if kept as a synchronous write, prefer the one-liner Path I/O form: `self.pid_file.write_text(str(os.getpid()))`.

## [No one-off vars and trivial wrappers] — additional findings

- **wt/tests/conftest.py**: 398–415 — Avoid `**{**defaults, **config_overrides}`; instantiate `ConfigFile` with explicit kwargs and `**config_overrides` at the end for clarity.

## [No useless documentation or comments](../../definitions/no-useless-docs.md)

- **wt/tests/conftest.py**: 391–394 — Helper docstring includes historical workflow; trim to describe only current behavior.
- **wt/tests/conftest.py**: 426 — Remove historical comment: "Config builder fixture removed - use config_factory directly".
- **wt/tests/conftest.py**: 302–308 — Shorten `real_temp_repo` docstring to a single descriptive line; drop compatibility notes.
- **wt/tests/conftest.py**: 312–337 — Trim `real_env` docstring and meta-comments; keep only non-obvious behavior.

## [Try/except is scoped around the operation it guards] — additional findings

- **wt/tests/conftest.py**: 236–251 — The catch for `ValueError`/`FileNotFoundError` swallows genuine errors (invalid PID) and mixes concerns; don’t suppress invalid PID — fail fast, and narrow exception scope to just the read.
- **wt/wt/server/wt_server.py**: 613–635 — In `PRService.get_pr_info`, a blanket `except Exception` in non-boundary code silently swallows errors and the try wraps a long block. Scope the try to just the GitHub call and catch specific expected exceptions (or let them propagate) with proper logging.

## [Time and duration use rich time types] — additional findings

- **wt/tests/conftest.py**: 192 — Use `datetime.timedelta` for timeouts and a deadline loop with `datetime` rather than `float` seconds with `time.time()`.

## [Imports at the top] — additional findings

- **wt/tests/conftest.py**: 217 — Move `from pathlib import Path as _P` to module top; avoid function-scope imports.


## [No dead code] — additional findings

- **wt/tests/conftest.py**: 122–124 — `empty_worktree_status()` is unused; delete the fixture.

## [No unnecessary line breaks](../../definitions/no-extra-linebreaks.md)
- **wt/tests/conftest.py**: 298–300 — Collapse multi-line assert into one line: `assert shutil.which("gitstatusd"), "integration tests require gitstatusd on PATH"`.
