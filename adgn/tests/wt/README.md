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

Fixtures live in `tests/conftest.py`. Use these consistently; do not duplicate fixtures inside test modules.

Core building blocks
- temp_dir (function) → Path: per-test scratch directory (backed by pytest tmp_path)
- isolated_git_env (function) → dict: hermetic git environment (HOME, XDG_CONFIG_HOME, GIT_CONFIG_*) to avoid reading user/system git config; use for any test that shells out to git
- repo_factory (function) → GitRepoFactory: creates real git repositories with configurable branches/commits/worktrees
- config_factory (function) → ConfigFactory(repo_path) → Configuration: writes a config.yaml under WT_DIR and returns resolved Configuration; ensures worktrees_dir exists

CLI/e2e environment
- real_temp_repo (function) → Path: a fresh main repo for integration/E2E
- real_env (function) → dict: environment for subprocess CLI invocations
  - Includes isolated_git_env
  - Sets WT_DIR to a unique per-test directory
  - Kills daemon pre- and post-test for that WT_DIR
  - Use for: any test that runs `python -m adgn.wt.cli ...` or `wt sh ...`
- real_env_with_existing_worktrees (function) → dict (and sometimes helpers): same as real_env, but pre-populates one or more worktrees using the real services; use when an initial set of worktrees is required

CLI helpers
- run_cli_command(args, cwd=None, env=None, timeout=60.0): runs `python -m adgn.wt.cli` with given args; automatically injects PYTHONPATH
- run_cli_sh_command(args, env, timeout=60.0): convenience wrapper for `wt sh ...`

Other utilities
- test_config → Configuration: minimal config for unit tests that need Configuration
- mock_factory → MockFactory: helpers to build mocks for GitHub etc.
- cli_runner → click.testing.CliRunner: for direct invocation of click commands where subprocess is not required
- kill_daemon_at_wt_dir(wt_dir: Path) → None: brutal cleanup of a daemon for a given WT_DIR; test-only

When to use which
- Unit tests (no subprocess, no daemon): repo_factory + config_factory + direct service instantiation (GitManager/WorktreeService). Avoid real_env and run_cli_command.
- Integration tests (CLI, real git, no fd3 semantics): real_temp_repo + real_env + run_cli_command. Keep timeouts modest (default 60s) but tests should finish quickly; slowness usually indicates isolation issues.
- E2E daemon tests (start the real daemon and exercise RPC): real_temp_repo + real_env; do not duplicate env creation in tests; rely on real_env to ensure per-test WT_DIR and cleanup.
- Shell/fd3 tests: real_temp_repo + real_env + run_cli_sh_command and assertions on fd3-captured output.

Rules and hygiene
- Do not define duplicate fixtures inside test modules. If you need a specialized variant (e.g., pre-existing worktrees), add it to conftest.py so all tests can reuse it. Replace local definitions named like `real_env_with_existing_worktrees` with the shared fixture.
- Always go through `real_env` for subprocess-based CLI tests; it guarantees hermetic git config and daemon cleanup. Never copy os.environ directly in tests that run the CLI.
- Each test should get a unique WT_DIR (provided by config_factory); never share the same WT_DIR between tests or parametrizations.
- If a CLI test times out, suspect environment isolation (WT_DIR collision, missing isolated_git_env) before increasing timeouts.
- Prefer factories (repo_factory, config_factory) over ad-hoc repo/config setup in tests; they encode the defaults and directories our code expects.

Migrating existing tests
- Consolidate any module-local fixtures that mirror conftest fixtures. For example, tests/e2e/test_real_workflow.py defines its own `real_env_with_existing_worktrees`; replace it with the shared fixture from conftest and, if needed, extend the conftest version to support your scenario.
- Ensure any `run_cli_command([...], env=..., timeout=...)` calls use the env from `real_env` or `real_env_with_existing_worktrees`. Do not build env by hand.

This guide is the single source of truth for test-fixture usage; update it when adding or changing fixtures.
