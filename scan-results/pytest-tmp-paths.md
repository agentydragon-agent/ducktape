# Pytest Temporary Path Antipatterns - Scan Results

## Summary

Scanned the ducktape codebase for pytest tests using manual `tempfile` module instead of pytest's built-in `tmp_path` and `tmp_path_factory` fixtures.

**Found:** 3 clear antipatterns + 1 borderline case

**Status:**
- ✅ **wt/tests/** - Already using pytest fixtures correctly (explicitly documented)
- ❌ **claude/claude_optimizer/tests/** - 2 antipatterns found
- ❌ **difftree/tests/** - 1 antipattern found
- ⚠️ **gatelet/gatelet/server/** - 1 borderline case (special environment constraints)
- ✅ **llm/mcp/habitify/examples/** - Not a pytest test (acceptable)
- ✅ **mcp_starter/** - Manual test script (acceptable)

---

## Clear Antipatterns (Should Fix)

### 1. claude/claude_optimizer/tests/conftest.py

**Location:** Lines 12-15

**Issue:** Using `tempfile.TemporaryDirectory()` in a pytest fixture instead of `tmp_path_factory`

**Current Code:**
```python
@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)
```

**Why it's an antipattern:**
- Manual temporary directory creation in a pytest fixture
- pytest provides `tmp_path` fixture for exactly this use case
- The fixture is reinventing what pytest already provides

**Recommended Fix:**
Remove this custom fixture entirely and use pytest's built-in `tmp_path` fixture directly in tests:

```python
# Before
def test_something(temp_dir):
    file = temp_dir / "test.txt"
    ...

# After
def test_something(tmp_path):
    file = tmp_path / "test.txt"
    ...
```

---

### 2. claude/claude_optimizer/tests/unit/test_config.py

**Location:** Lines 27-36

**Issue:** Using `tempfile.NamedTemporaryFile()` with manual cleanup instead of `tmp_path`

**Current Code:**
```python
def test_config_from_file():
    """Test loading config from YAML file."""
    config_data = { ... }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)

    try:
        config = OptimizerConfig.from_file(config_path)
        assert config.rollouts.max_parallel == 4
        assert "*.log" in config.exclude_patterns
    finally:
        config_path.unlink()
```

**Why it's an antipattern:**
- Manual temporary file creation with `delete=False`
- Manual cleanup in `finally` block
- pytest provides automatic cleanup
- More error-prone (what if `unlink()` fails?)

**Recommended Fix:**
Use `tmp_path` fixture:

```python
def test_config_from_file(tmp_path):
    """Test loading config from YAML file."""
    config_data = { ... }

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config_data))

    config = OptimizerConfig.from_file(config_path)
    assert config.rollouts.max_parallel == 4
    assert "*.log" in config.exclude_patterns
    # No cleanup needed - pytest handles it!
```

---

### 3. difftree/tests/conftest.py

**Location:** Lines 81-100

**Issue:** Using `tempfile.TemporaryDirectory()` in a session/module fixture instead of `tmp_path_factory`

**Current Code:**
```python
@pytest.fixture
def temp_git_repo() -> Generator[Path, None, None]:
    """
    Create a temporary git repository for E2E testing.

    Yields:
        Path to the temporary git repository.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
        # Disable commit signing for tests
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo_path, check=True, capture_output=True)

        yield repo_path
```

**Why it's an antipattern:**
- Manual temporary directory creation for test fixture
- Should use pytest's `tmp_path_factory` for custom fixtures that need temp directories
- Less control over cleanup and retention for debugging

**Recommended Fix:**
Use `tmp_path_factory`:

```python
@pytest.fixture
def temp_git_repo(tmp_path_factory) -> Path:
    """
    Create a temporary git repository for E2E testing.

    Returns:
        Path to the temporary git repository.
    """
    repo_path = tmp_path_factory.mktemp("git_repo")

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
    # Disable commit signing for tests
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo_path, check=True, capture_output=True)

    return repo_path
    # No cleanup needed - pytest handles it!
```

---

## Borderline Cases (Consider Fixing)

### 4. gatelet/gatelet/server/conftest.py

**Location:** Lines 52, 70

**Issue:** Using `tempfile.mkdtemp()` for PostgreSQL data directory with manual cleanup

**Current Code:**
```python
@pytest.fixture(scope="session", autouse=True)
def _postgres():
    """Start and stop a temporary PostgreSQL server if needed."""

    # ... CI checks ...

    # In Codex environment, set up a temporary PostgreSQL server
    if os.environ.get("IS_CODEX_ENV") != "1":
        yield
        return

    datadir = tempfile.mkdtemp(prefix="pgdata-")
    subprocess.check_call(["chown", "-R", "postgres:postgres", datadir])
    # ... PostgreSQL setup ...
    try:
        yield
    finally:
        subprocess.check_call(["sudo", "-u", "postgres", str(pg_ctl), "-D", datadir, "-m", "fast", "stop"])
        shutil.rmtree(datadir)
```

**Why it might be acceptable:**
- Special environment constraints (Codex environment check)
- Needs to set specific ownership (`chown` to `postgres:postgres`)
- Has proper cleanup in `finally` block
- PostgreSQL server setup is complex and may require specific directory permissions

**Why it could still be improved:**
- Could use `tmp_path_factory` and then `chown` the directory
- Would get pytest's benefits (retention on failure, configurable base temp dir)

**Recommended Fix (if desired):**
```python
@pytest.fixture(scope="session", autouse=True)
def _postgres(tmp_path_factory):
    """Start and stop a temporary PostgreSQL server if needed."""

    # ... CI checks ...

    # In Codex environment, set up a temporary PostgreSQL server
    if os.environ.get("IS_CODEX_ENV") != "1":
        yield
        return

    datadir = tmp_path_factory.mktemp("pgdata")
    subprocess.check_call(["chown", "-R", "postgres:postgres", str(datadir)])
    # ... PostgreSQL setup ...
    try:
        yield
    finally:
        subprocess.check_call(["sudo", "-u", "postgres", str(pg_ctl), "-D", str(datadir), "-m", "fast", "stop"])
        # No manual cleanup needed - pytest handles it!
```

**Verdict:** Borderline - could be left as-is due to special requirements, but would benefit from pytest fixtures.

---

## Non-Issues (Correctly Excluded)

### 5. llm/mcp/habitify/examples/test_mcp_dev.py

**Location:** Lines 74-76

**Status:** ✅ Acceptable

**Reason:**
- Located in `examples/` directory, not a pytest test
- Using `tempfile.NamedTemporaryFile()` to create a file to pass to external command
- Has proper cleanup (lines 107-111)
- This is example/demonstration code, not automated tests

---

### 6. mcp_starter/manual_test_sdk.py

**Location:** Line 235

**Status:** ✅ Acceptable

**Reason:**
- Manual test script (not pytest)
- Using `tempfile.mkdtemp()` to create cwd for ClaudeSDKClient
- Not part of automated test suite
- Filename explicitly says "manual_test"

---

### 7. wt/tests/e2e/test_real_workflow.py

**Location:** Throughout file

**Status:** ✅ Already correct

**Evidence:** Comment at line 33 explicitly states:
```python
"""
Test Architecture
=================

These tests use proper isolation patterns:
- pytest's tmp_path fixture (not tempfile.TemporaryDirectory)
```

This test suite is already following best practices!

---

## Impact Analysis

### High Priority Fixes
1. **claude/claude_optimizer/tests/conftest.py** - Custom fixture duplicates pytest functionality
2. **claude/claude_optimizer/tests/unit/test_config.py** - Manual cleanup is error-prone

### Medium Priority Fixes
3. **difftree/tests/conftest.py** - Would benefit from pytest's tmp_path_factory

### Low Priority (Optional)
4. **gatelet/gatelet/server/conftest.py** - Works correctly but could use pytest fixtures

---

## Benefits of Fixing

✅ **Automatic cleanup** - No finally blocks, no forgotten cleanup
✅ **Unique per test** - Each test gets fresh directory, no conflicts
✅ **Pathlib by default** - `tmp_path` is `Path`, not string
✅ **Configurable retention** - `pytest --basetemp` to inspect failed test artifacts
✅ **Better errors** - pytest shows temp dir location on failure
✅ **Scoping support** - function/class/module/session scopes via `tmp_path_factory`

---

## References

- [pytest tmp_path docs](https://docs.pytest.org/en/stable/how-to/tmp_path.html)
- [pytest fixtures](https://docs.pytest.org/en/stable/reference/fixtures.html#tmp-path)
- Scan prompt: `/home/user/ducktape/prompts/scans/pytest-tmp-paths.md`
