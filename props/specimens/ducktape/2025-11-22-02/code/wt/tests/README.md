# wt Test Suite

Includes shell integration tests.

## Test Structure

### Test Types

- **Unit Tests** (`@pytest.mark.unit`): Test individual components in isolation
- **Integration Tests** (`@pytest.mark.integration`): Test CLI commands with real git operations
- **Shell Integration Tests** (`@pytest.mark.shell`): Test the fancy fd3 shell integration

### Test Files

- `test_manager.py` - Unit tests for WorktreeManager core functionality
- `test_command_handlers.py` - Unit tests for CLI command handlers
- `test_cli_integration.py` - Integration tests for CLI with real git repos
- `test_shell_integration.py` - **Shell integration tests with fd3 command emission**

## Running Tests

```bash
# Unit tests only (fast)
pytest -m unit

# Integration tests only (slower, creates real git repos)
pytest -m integration

# Shell integration tests (tests actual shell function with fd3)
pytest -m shell

# Exclude slow tests
pytest -m "not slow"

# Run with coverage
pytest --cov=wt --cov-report=term-missing
```

## Shell Integration Tests

The shell integration tests (`test_shell_integration.py`) test the **actual shell integration** with fd3 command emission. These tests:

1. **Create real git repositories** using pytest fixtures
2. **Invoke the actual shell function** via subprocess
3. **Test fd3 command emission** by redirecting fd3 to stdout
4. **Verify different scenarios**:
   - ✅ **Success teleport** - cd command emitted to fd3
   - ❌ **Managed error** - controlled_error with cd command to navigate away
   - 💥 **Unhandled error** - no fd3 commands emitted

### Key Test Scenarios

- `test_successful_teleport_with_fd3` - Tests successful navigation with cd command
- `test_managed_error_with_fd3_commands` - Tests controlled errors that emit commands
- `test_unhandled_error_no_fd3_emission` - Tests unhandled errors (no fd3 output)
- `test_worktree_creation_with_navigation` - Tests create → navigate flow
- `test_multiple_fd3_commands_in_sequence` - Tests complex command sequences

## Fixture catalog and usage guide

Fixtures live in `tests/conftest.py`. Use these consistently; do not duplicate fixtures in test modules.

Core building blocks
- `temp_dir` → Path: per-test scratch directory (backed by pytest `tmp_path`).
- `repo_factory` → GitRepoFactory: creates real git repositories with configurable branches/commits/worktrees.
- `config_factory(repo_path)` → ConfigFactory: writes a config.yaml under WT_DIR and returns resolved `Configuration`; ensures `worktrees_dir` exists.
- Hermetic git env: applied automatically by an autouse fixture; sets `HOME`/`XDG_CONFIG_HOME` to avoid reading user/system git config.

CLI/e2e environment
- `real_temp_repo` → Path: a fresh main repo for integration/E2E.
- `real_env` → dict: environment for subprocess CLI invocations.
  - Applies hermetic git env via autouse.
  - Sets `WT_DIR` to a unique per-test directory.
  - Cleanly shuts down the daemon pre- and post-test for that `WT_DIR`.
  - Use for any test that runs `python -m wt.cli ...` or `wt sh ...`.
- `real_env_with_existing_worktrees` → dict: like `real_env`, but pre-populates worktrees using real services; use when an initial set of worktrees is required.
- `wt_env` → Path: sets `WT_DIR` for Click-based CLI tests (no subprocess), removing the need to repeat `monkeypatch.setenv`.

CLI helpers
- `run_cli_command(args, cwd=None, env=None, timeout=60.0)` – runs `python -m wt.cli` with given args.
- `run_cli_sh_command(args, env, timeout=60.0)` – convenience wrapper for `wt sh ...`.
- `shell_runner` – helper to install and invoke the shell function in a subprocess for fd3 scenarios.

Shared builders
- `build_status_response(results: dict[str|WorktreeID, StatusResult]) -> StatusResponse` – create a typed `StatusResponse` for Click-based CLI tests. Prefer this over ad‑hoc builders inside tests.

Example:
```
from wt.shared.protocol import StatusResult, CommitInfo, WorktreeID

@patch("wt.client.wt_client.WtClient.get_status")
def test_ls_with_data(mock_get_status, wt_env, build_status_response):
    result = StatusResult(
        wtid="test",
        name="test",
        branch_name="test/x",
        upstream_branch="main",
        absolute_path="/tmp/test",
        dirty_files_lower_bound=0,
        untracked_files_lower_bound=0,
        ahead_count=0,
        behind_count=0,
        pr_info=PRInfoDisabled(),
        commit_info=CommitInfo(hash="abc", short_hash="abc", message="m", author="a", date="2024-01-01T00:00:00"),
        processing_time_ms=1.0,
        last_updated_at=datetime.now(),
    )
    mock_get_status.return_value = build_status_response({WorktreeID("wtid:test"): result})
    out = CliRunner().invoke(main, ["ls"]).output
    assert "test" in out
```

Other utilities
- `test_config` → Configuration: minimal config for unit tests that need Configuration.
- `mock_factory` → MockFactory: helpers to build mocks for GitHub etc.
- `cli_runner` → click.testing.CliRunner: for direct invocation of Click commands (no subprocess).
- `kill_daemon_at_wt_dir(wt_dir: Path)` → None: clean shutdown and verification for a given `WT_DIR`.

When to use which
- Unit tests (no subprocess, no daemon): `repo_factory` + `config_factory` + direct service instantiation (`GitManager`/`WorktreeService`). Avoid `real_env`/`run_cli_command`.
- Integration tests (CLI, real git, no fd3 semantics): `real_temp_repo` + `real_env` + `run_cli_command`.
- E2E daemon tests (start the real daemon and exercise RPC): `real_temp_repo` + `real_env`; rely on `real_env` to ensure per-test WT_DIR and cleanup.
- Shell/fd3 tests: `real_temp_repo` + `real_env` + `shell_runner`/`run_cli_sh_command`, with assertions on fd3-captured output.

Rules and hygiene
- Do not define duplicate fixtures inside test modules. If you need a specialized variant (e.g., pre-existing worktrees), add it to `conftest.py` so all tests can reuse it.
- Always go through `real_env` for subprocess-based CLI tests; it guarantees hermetic git config and daemon cleanup. Never build env by copying `os.environ` directly.
- Each test should get a unique WT_DIR (via `config_factory`/`real_env`). Never share the same WT_DIR between tests or parametrizations.
- If a CLI test times out, suspect environment isolation (WT_DIR collision or missing hermetic env) before increasing timeouts.
- Prefer factories (`repo_factory`, `config_factory`) over ad‑hoc repo/config setup; they encode expected defaults and directories.
- Do not define local status-response builders; use the shared `build_status_response` fixture.

Migrating existing tests
- Consolidate any module-local fixtures that mirror conftest fixtures. For example, tests/e2e/test_real_workflow.py defines its own `real_env_with_existing_worktrees`; replace it with the shared fixture from conftest and, if needed, extend the conftest version to support your scenario.
- Ensure any `run_cli_command([...], env=..., timeout=...)` calls use the env from `real_env` or `real_env_with_existing_worktrees`. Do not build env by hand.

This guide is the single source of truth for test-fixture usage; update it when adding or changing fixtures.
