# adgn-worktree Test Suite

This directory contains comprehensive tests for the adgn-worktree tool, including the shell integration tests requested in the GitHub review comments.

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

## Test Fixtures

The test suite uses comprehensive fixtures defined in `conftest.py`:

- `git_repo` - Creates a real git repository with initial commit
- `worktrees_dir` - Creates worktrees directory  
- `test_config` - Provides test configuration using build_test_configuration helper
- `real_worktree_service` - Real WorktreeService with mocked GitHub interface
- `mock_github_interface` - Mocks GitHub API to avoid network calls
- `temp_config_file` - Creates temporary WT_DIR configuration for testing
- `config_builder` - Helper to build custom configurations for tests
- `real_temp_repo` - Real git repository for integration tests
- `real_env` - Sets up WT_DIR environment with daemon cleanup

## Recent Test Improvements

### ✅ Modern Mock Patterns
All tests now use **decorator-style patches** instead of context managers:
```python
@patch("wt.client.wt_client.WtClient.get_status")
def test_something(self, mock_get_status, ...):
    mock_get_status.return_value = create_test_status_response()
```

### ✅ Centralized Configuration Building  
Tests use the `build_test_configuration()` helper for consistent config creation:
```python
config = build_test_configuration(
    repo_path,
    branch_prefix="test/",
    upstream_branch="main"
)
```

### ✅ Better Fixture Organization
- Removed deprecated `Services` container patterns
- Direct dependency injection in tests
- Cleaner test setup with explicit dependencies
