# TODO - verify

- **Forbid Dynamic Attribute Access** .../shared/logging_config.py:98 — Uses getattr(logging, ...) to derive level; avoid dynamic attribute probing.
**Time And Duration Use Rich Time Types**
- Float epochs used in core logic; prefer timezone-aware datetimes/timedeltas or monotonic for durations.
  - .../shared/github_models.py:105, 118, 121, 134 (time.time() timestamps, cache_expiration seconds)
  - .../server/wt_server.py:90 (handshake timestamp), 229, 310–311, 341, 365, 402–403 (time.time() in refresh/WorktreeInfo), 883, 955 (naive datetime.now())

- .../tests/test_utils.py:14–21 **Broad except wraps multiple unrelated statements**; narrow scope and catch specific exceptions.
- **Pathlib usage: replace open() with Path.open()** wt/wt/shared/configuration.py:126 wt/wt/client/handlers.py:287 wt/wt/client/wt_client.py:59 wt/wt/server/wt_server.py:2501

**Uses str.removeprefix / str.removesuffix**
- Fixed-prefix removal via slicing; use removeprefix instead. .../shared/models.py:50, 52, .../server/worktree_service.py:252, 259

Async I/O: blocking file open in async context
- wt/wt/server/wt_server.py:2501 — async method opens file with blocking open()

Async tasks: lost task handles
- wt/wt/server/wt_server.py:2517, 2563 — store result of asyncio.create_task to avoid orphaned tasks

Subprocess safety audit (bandit B603): ensure inputs are trusted/sanitized
- wt/wt/server/wt_server.py:1267, 1290
- wt/wt/shared/git_utils.py:27

List construction style: prefer unpack over list concatenation
- wt/wt/shared/git_utils.py:26 — use ["git", "-c", "core.hooksPath=", *args]

Cyclomatic complexity (radon): consider refactoring to reduce complexity
- wt/wt/cli.py: _async_sh_main (D, 23) at 172
- wt/wt/server/wt_server.py: WtDaemon._handle_status_request (D, 27) at 1595; handle_client_request (C, 18) at 1472; _handle_worktree_create_request (C, 14) at 1945; GitStatusdProcess._get_github_pr_info (C, 12) at 997; _update_cache_from_gitstatusd (C, 11) at 803; _validate_configuration (C, 12) at 1319
- wt/wt/client/wt_client.py: WtClient.create_worktree (D, 27) at 374; _start_daemon_if_needed (C, 14) at 76
- wt/wt/client/handlers.py: handle_status (C, 12) at 4
- wt/wt/client/view_formatter.py: ViewFormatter.format_status_row (C, 13) at 74
- wt/wt/server/gitstatusd_client.py: GitStatusdResponse.branch_status (C, 12) at 143
