# TODO - verify

- **Forbid Dynamic Attribute Access** .../shared/logging_config.py:98 — Uses getattr(logging, ...) to derive level; avoid dynamic attribute probing.
**Time And Duration Use Rich Time Types**
- Float epochs used in core logic; prefer timezone-aware datetimes/timedeltas or monotonic for durations.
  - .../shared/github_models.py:105, 118, 121, 134 (time.time() timestamps, cache_expiration seconds)
  - .../server/wt_server.py:90 (handshake timestamp), 229, 310–311, 341, 365, 402–403 (time.time() in refresh/WorktreeInfo), 883, 955 (naive datetime.now())

- .../client/view_formatter.py:114, 179, 300 **Manual URL construction** via f-strings; use urllib.parse helpers. 
- .../tests/test_utils.py:14–21 **Broad except wraps multiple unrelated statements**; narrow scope and catch specific exceptions.
- **Pathlib usage: replace open() with Path.open()** wt/wt/shared/configuration.py:126 wt/wt/client/handlers.py:287 wt/wt/client/wt_client.py:59 wt/wt/server/wt_server.py:2501

**Uses str.removeprefix / str.removesuffix**
- Fixed-prefix removal via slicing; use removeprefix instead. .../shared/models.py:50, 52, .../server/worktree_service.py:252, 259

Async I/O: blocking file open in async context
- wt/wt/server/wt_server.py:2501 — async method opens file with blocking open()

Async tasks: lost task handles
- wt/wt/server/wt_server.py:2517, 2563 — store result of asyncio.create_task to avoid orphaned tasks

Type consistency: mixed types assigned to same variable
- wt/wt/server/wt_server.py:1024 — cache_age set to float or "never"; use consistent type

URLs: built via string concatenation instead of stdlib helpers
- wt/wt/client/view_formatter.py:114, 179, 300 — build links with urllib.parse (e.g., urlunparse)

Security: weak hash and hardcoded tmp path
- wt/wt/shared/configuration.py:74–75 — md5 used for path hashing and hardcoded “/tmp”; prefer hashlib.blake2/sha256 or md5(..., usedforsecurity=False) and tempfile.gettempdir()

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

# VERIFIED - To commit

wt_server.py: _compute_teleport_target should return Path not str (saves conversions)

---
```
            if current_relative_path:  # <- L2359
                current_dir = target_path / current_relative_path
            else:
                current_dir = target_path
```
should simplify to:
```
current_dir = target_path
if current_relative_path:
    current_dir = current_dir / current_relative_path
```

---

wt_server.py: _record_github_error is dead code. so is WorktreeRuntime and StatusSnapshot.
StatusSnapshot should probably be wired into `build_status_snapshot` on gitstatusd handled class.
`_update_comprehensive_cache` also returns what might be the same object.

---

wt_server.py `_update_comprehensive_cache`: the word "comprehensive" here is just meaningless fluff that doesn't add any information.
remove.

---

wt_server.py write_startup_handshake: handshake protocol should be pydantic model not raw dict; should be shared with client via shared files.
not handled as raw dict.

`self.cached_working_status: tuple[list[str], list[str]] | None = None` - completely untyped typle of list[str] does not say what it contains.
should have more descriptive name or type that's descriptive, e.g. dataclass possibly.

_refresh_gituhb_cache silenlty swallows errors without raising some kind of error signal on the github info cache.

`# Old filesystem watching variables removed - now handled by DebouncedGitHubRefresh` - not useful historical  comment, should be removed

`GitStatusdProcess` class handles not just gitstatusd but also has *github* handling code which is a separate concern.
that should not be bundled in the same class. or renamed to explain that it actually does not handle *just* gitstatusd.
butr name of class implies intent to have it manage *just* the separate gitstatusd concern.

redundant conditional, remove:
```
        if worktree_info.path in self.gitstatusd_clients:  # L1425
            return  # Already managed

        if worktree_info.path in self.gitstatusd_clients:
            return
```


this should be walrus:
```
            # Read request line
            data = await reader.readline()  # L1482
            if not data:
                return
```

this is a useless wrapper, should remove and just use `Response` inline:
```
    def _create_success_response(self, result: Any, request_id: uuid.UUID) -> Response:
        """Create a successful JSON-RPC response."""
        return Response(result=result, id=request_id)
```

`execute_post_creation_script` should take script path as `Path`, not `str`. same with `_run_post_creation_script`.

`wt_server.py`'s `__main__` block should be deleted - server is started from central wt cli entry point in `wt/cli.py`.

client `handlers.py`: import->top L16 L10 L97 L94 L86 L75 L104 L127 L120 L134 L136 L194 L196 L238-243 L249 L277 L342 L201 L164-168 L152 L142 L86 L94 L75

```
async def handle_status(daemon_client, formatter) -> None:  # L4
    """Handle the default status display command."""
```
useless docstring, delete.

Imports inside functions (should be at module top per imports-top)
- wt/tests/conftest.py:109, 111, 212, 217, 296, 354

Naming/style: avoid importing CamelCase as ALL_CAPS-like alias
those should both just be standard imports to the top
- wt/tests/conftest.py:217 — “from pathlib import Path as _P”
- wt/tests/e2e/test_path_watcher_integration.py:60 — “from pathlib import Path as _P”

Type hints: None default for non-Optional parameter
- wt/wt/server/wt_server.py:72 — error_message default None but annotated as str; annotate as str | None

wrong type annotation / boolean api returns non-boolean:
- wt/wt/server/wt_server.py:1142 — is_running returns Process | bool | None via “and” expression; coerce to bool

===================

also split-off changes to personal/agentydragon/adgn_utils/adgn_utils/adgn_expose.py


add the following real findings into the 2025-09-02 wt specimen following our conventions.
in specimen's 'work/' dir is the cloned repo, use for reference & to find proper line numbers.

-------
-------
# THROWN IN
-------
-------
```
@pytest.fixture
def real_env(real_temp_repo, config_factory):
    """Set up real environment for integration tests with proper cleanup.

    Creates real configuration and environment setup for tests that need
    to interact with actual daemon processes and gitstatusd.
    """
    # Explicit requirement checks

    # Kill any existing daemon first
    kill_daemon_and_verify(real_temp_repo)

    # Create config using factory pattern
    factory = config_factory(real_temp_repo)
    config = factory.integration(github_enabled=False)

    # Set up environment
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)

    # Assume package is properly installed and importable

    yield env

    # Cleanup: Kill daemon after test
    kill_daemon_and_verify(real_temp_repo)
```

too many legacy-related detail comments that are not helpful, including the daemon kills.
should not declare "we are doing the thing correctly". just do the thing correctly.

```
@pytest.fixture
def real_env(real_temp_repo, config_factory):
    """Real environment for integration tests (daemon, repo)."""
    kill_daemon_and_verify(real_temp_repo)

    config = config_factory(real_temp_repo).integration(github_enabled=False)

    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)

    yield env

    kill_daemon_and_verify(real_temp_repo)
```

.... at least shortened like this. but kill_daemon_and_verify should in fact be
done either by a *wrapper yield fixture* or shared teardown which auto-tears-down.

-----

```
def kill_daemon_and_verify(repo_path: Path, timeout: float = 5.0):   # <- L192
    """Kill daemon using CLI command and verify it's gone.

    CRITICAL for test isolation. This function ensures that:

    1. Daemon is killed using the actual CLI kill-daemon command (not raw kill)
    2. Process termination is verified by checking PID file and process existence
    3. Test fails if daemon doesn't terminate within timeout (indicates stuck daemon)
    4. Socket cleanup is verified to ensure no leftover daemon state

    This prevents daemon interference between tests, which was causing sporadic
    test failures when daemons from previous tests were still running.

    Args:
        repo_path: Path to test repository (used to find daemon files)
        timeout: Max seconds to wait for daemon termination (default 5.0)

    Raises:
        pytest.fail: If daemon doesn't terminate within timeout period
    """
    from .test_utils import run_cli_command

    env = os.environ.copy()
    env["WT_DIR"] = str((repo_path / ".wt").resolve())
    # Ensure -m wt.cli works without install
    from pathlib import Path as _P

    project_root = str(_P(__file__).resolve().parents[1])
    env["PYTHONPATH"] = f"{project_root}:{env.get('PYTHONPATH', '')}"

    # Run kill-daemon command
    run_cli_command(["sh", "kill-daemon"], env=env)

    # Don't assert success here - daemon might not be running, which is fine

    # Wait and verify daemon is gone
    daemon_dir = repo_path / ".wt"
    pid_file = daemon_dir / "daemon.pid"

    start_time = time.time()
    while time.time() - start_time < timeout:
        if not pid_file.exists():
            return  # Daemon is gone

        try:
            pid_content = pid_file.read_text().strip()
            if not pid_content:
                return  # Empty PID file means daemon is gone

            pid = int(pid_content)

            # Check if process still exists
            try:
                os.kill(pid, 0)  # Signal 0 just checks if process exists
                time.sleep(0.1)  # Process still exists, wait a bit more
            except (OSError, ProcessLookupError):
                return  # Process is gone

        except (ValueError, FileNotFoundError):
            return  # Invalid PID or file gone

    # If we get here, daemon didn't shut down in time
    if pid_file.exists():
        try:
            pid_content = pid_file.read_text().strip()
            if pid_content:
                pytest.fail(
                    f"Daemon with PID {pid_content} did not shut down within {timeout} seconds",
                )
        except (OSError, UnicodeDecodeError) as e:
            # If we can't read the PID file, still fail but with a more specific error
            pytest.fail(
                f"Daemon cleanup verification failed - could not read PID file: {e}",
            )

    pytest.fail(f"Daemon cleanup verification failed after {timeout} seconds")
```

way too verbose. shorten messages to fit on one line. do not catch rare errors to just relabel them.
do not swallow invalid PID, that's a real error.
the "pid file still exists after cleanup" check is way too complicated, tries to check like 37 separate
different cases when really "if the file still exists -> shutdown failed, therefore that's an error because
daemon is hung". should just shortcut to quick fail.
don't duplicate computing wt_path. no necessary stringification.
imports to the top.
variable timeout parameter is not useful.
use datetime not raw numeric time.
daemon and pid file check is separate, that should not be the case.
we are also not checking against failure of "daemon pid changed" which - would be an optional check but if we're writing this as thoroughly as this code is, we might as well include it.

`repo_path` being used to find `.wt` file also goes against domain! `WT_DIR` should be passed in - possibly as fixture.
reading the source code & design would reveal location of wt_dir and repos is independent!
tests should be refactored to pass in wt_dir explicitly here, OR to refactor this to take and possibly be a pytest fixture
(see above re auto teardown). some test files may already do this.

```
def kill_daemon_and_verify(repo_path: Path):   # <- L192
    """Kill daemon using CLI command and verify it's gone.

    This isolates tests, preventing interference from daemon lingering between tests.

    Kill daemon using actual CLI kill-daemon command (instead of raw kill - serves as integration test)
    Process termination is verified by checking PID file and process existence

    Args:
        repo_path: Path to test repository (used to find daemon files)
    """
    wt_dir = repo_path / ".wt"

    env = os.environ.copy()
    env["WT_DIR"] = str(wt_dir.resolve())
    project_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = f"{project_root}:{env.get('PYTHONPATH', '')}"

    run_cli_command(["sh", "kill-daemon"], env=env)

    pid_file = wt_dir / "daemon.pid"

    if not pid_file.exists() or not (pid_content := pid_file.read_text().strip()):
        pid = int(pid_content)

    deadline = datetime.datetime.now() + datetime.timedelta(seconds=5)
    while datetime.datetime.now() < deadline:
        try:
            os.kill(pid, 0)  # Signal 0 just checks if process exists
        except (OSError, ProcessLookupError):
            assert not pid_file.exists() or not pid_file.read_text().strip(), "Daemon left stale PID file"
            return

        # Process still exists, wait a bit more
        time.sleep(0.1)

    pytest.fail("Daemon didn't shut down in time")
```

---

empty_worktree_status() is dead code.
