# Scan Results: Duplicated Test Code

**Scan Date**: 2025-11-19
**Scope**: Full repository test files
**Status**: Complete

---

## Executive Summary

This scan identified **multiple instances of duplicated test infrastructure** across the codebase, with the most significant patterns in:

1. **Fixtures** (4 duplicates found across 3 test modules)
2. **Mock configurations** (5+ duplicated patterns)
3. **Test data** (repeated mock response structures)
4. **Assertion patterns** (26+ instances of identical assertions)
5. **Setup logic** (repeated subprocess/Docker initialization)

**Priority**: The `claude_linter_v2` test suite has the highest concentration of duplicates and should be refactored first.

---

## Pattern 1: Duplicated Fixtures (HIGH PRIORITY)

### Issue: Fixture redefinition across modules

#### Location 1: `session_id` fixture (4 files)

Duplicate fixture definitions for `session_id`:

**Files:**
- `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_mcp_tools.py` (lines 25-27)
- `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_stop_hook_quality_gate.py` (lines 19-21)
- `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_stop_hook_gitignore.py` (lines 21-24)
- `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_stop_hook_fresh_scan.py` (lines 20-22)

**Current Implementation:**

```python
# test_mcp_tools.py
@pytest.fixture
def session_id(self) -> SessionID:
    """Valid session ID."""
    return SessionID("550e8400-e29b-41d4-a716-446655440000")

# test_stop_hook_*.py
@pytest.fixture
def session_id():
    """Create a test session ID."""
    return parse_session_id("12345678-1234-5678-1234-567812345678")
```

**Issue**: Same fixture name defined in 4 test files, with slightly different implementations (different session ID values, different return types).

**Recommendation**: Create `conftest.py` in `claude_linter_v2/` directory and consolidate.

---

#### Location 2: `handler` fixture (4 files)

Duplicate fixture definitions for `handler`:

**Files:**
- `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_mcp_tools.py` (lines 20-22)
- `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_stop_hook_quality_gate.py` (lines 10-15)
- `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_stop_hook_gitignore.py` (lines 13-18)
- `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_stop_hook_fresh_scan.py` (lines 11-16)

**Current Implementation:**

```python
# test_mcp_tools.py
@pytest.fixture
def handler(self):
    """Create a handler instance."""
    return HookHandler()

# test_stop_hook_*.py
@pytest.fixture
def handler():
    """Create a hook handler instance."""
    handler = HookHandler()
    # Ensure quality gate is enabled for testing
    handler.config_loader.config.hooks["stop"].quality_gate = True
    return handler
```

**Issue**: Different implementations of `handler` fixture. Some enable quality gate, others don't. This inconsistency could lead to subtle test behavior differences.

**Recommendation**: Create a shared fixture in `conftest.py` with optional parameter for quality gate, or create two variants (`handler` and `handler_with_quality_gate`).

---

#### Location 3: `temp_db` and `test_config` fixtures (2 files each)

**Files with `test_config`:**
- `/home/user/ducktape/wt/tests/conftest.py`
- Another location (found via grep)

**Files with `temp_db`:**
- Multiple test modules

**Recommendation**: Verify that these are intentionally different or can be consolidated.

---

## Pattern 2: Duplicated Mock Configurations (MEDIUM PRIORITY)

### Issue: Repeated subprocess.run mock patterns

**Frequency**: 10+ instances of `@patch("subprocess.run")` with similar setup

**Example 1: Python formatter tests**

`/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_python_formatter.py`:

```python
@patch("subprocess.run")
def test_format_code_with_black_formatter(self, mock_run):
    # Mock black output
    formatted_code = "def hello():\n    print('Hello, world!')\n"
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=formatted_code,
        stderr="",
    )
    # ... test logic
```

**Example 2: Python ruff tests**

`/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_python_ruff.py`:

```python
@patch("subprocess.run")
def test_check_code_clean(self, mock_run):
    code = """..."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    # ... test logic
```

**Issue**: Same pattern repeated across multiple test files. The mock setup could be extracted to a fixture.

**Recommendation**: Create shared fixtures for common mock patterns:

```python
# conftest.py
@pytest.fixture
def mock_subprocess_success(monkeypatch):
    """Mock successful subprocess.run call."""
    def _mock(stdout="", stderr=""):
        from unittest.mock import MagicMock
        mock = MagicMock(returncode=0, stdout=stdout, stderr=stderr)
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock)
        return mock
    return _mock
```

---

## Pattern 3: Duplicated Assertion Patterns (MEDIUM PRIORITY)

### Issue: Repeated assertion sequences

**Frequency**: 26+ identical assertion patterns found

**Most Common Patterns:**

1. **Exit code assertions** (26 instances):
   ```python
   assert result.returncode == 0  # or exit_code
   ```

2. **Violation count assertions** (10+ instances):
   ```python
   assert len(violations) == 1
   assert len(violations) == 0
   ```

3. **JSON response assertions** (4+ instances):
   ```python
   assert response.json() == {"status": "ok"}
   assert response.status_code == 200
   ```

4. **Mock return value assertions** (5+ instances):
   ```python
   mock_run.return_value = MagicMock(
       returncode=1,
       stdout=ruff_output,
       stderr=""
   )
   ```

**Recommendation**: Create custom assertion helpers in a shared module:

```python
# tests/helpers.py or conftest.py

def assert_command_success(result, expected_output=None):
    """Assert successful command execution."""
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    if expected_output:
        assert expected_output in result.stdout

def assert_no_violations(violations):
    """Assert no violations found."""
    assert len(violations) == 0, f"Expected no violations, found {len(violations)}"

def assert_single_violation(violations, expected_rule=None):
    """Assert exactly one violation found."""
    assert len(violations) == 1
    if expected_rule:
        assert violations[0].rule == expected_rule
```

---

## Pattern 4: Duplicated Test Data (MEDIUM PRIORITY)

### Issue: Repeated mock data structures

**Example: Subprocess output patterns**

Multiple test files define identical mock subprocess responses:

```python
# Repeated in test_python_ruff.py, test_python_formatter.py, etc.
mock_run.return_value = MagicMock(
    returncode=0,
    stdout="",
    stderr="",
)

# Repeated in multiple tests with similar structure
ruff_output = json.dumps([
    {
        "code": "E722",
        "message": "Do not use bare `except`",
        "location": {"row": 4, "column": 1},
        "fix": None
    }
])
```

**Recommendation**: Create factory functions for test data:

```python
# tests/data/factories.py
import json

def make_ruff_violation(code="E722", row=4, column=1, message="Do not use bare `except`"):
    """Factory for ruff violation JSON."""
    return {
        "code": code,
        "message": message,
        "location": {"row": row, "column": column},
        "fix": None
    }

def make_subprocess_result(returncode=0, stdout="", stderr=""):
    """Factory for subprocess result."""
    from unittest.mock import MagicMock
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)
```

---

## Pattern 5: Duplicated Setup Logic (MEDIUM PRIORITY)

### Issue: Repeated git initialization code

Found in multiple test files:

```python
# test_stop_hook_gitignore.py, test_e2e.py, etc.
subprocess.run(["git", "init"], check=True)
subprocess.run(["git", "config", "user.email", "test@example.com"], check=True)
subprocess.run(["git", "config", "user.name", "Test User"], check=True)
subprocess.run(["git", "config", "commit.gpgsign", "false"], check=True)
```

**Frequency**: 3+ instances

**Recommendation**: Create a fixture (already exists in `difftree/tests/conftest.py`):

```python
# conftest.py
@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repository for testing."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    return tmp_path
```

**Status**: Already implemented in `difftree/tests/conftest.py`, but NOT in `claude_linter_v2/tests/`.

---

## Pattern 6: Missing conftest.py Files (HIGH PRIORITY)

### Issue: No conftest.py in test directory

**Directory**: `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/`

**Impact**: Fixtures cannot be shared across test modules in this directory, forcing duplication.

**Recommendation**: Create `conftest.py` with shared fixtures:

```python
# claude_linter_v2/conftest.py
"""Shared fixtures for claude_linter_v2 tests."""

from ducktape_llm_common.claude_linter_v2.hooks.handler import HookHandler
from ducktape_llm_common.claude_linter_v2.types import parse_session_id
import pytest

@pytest.fixture
def handler():
    """Create a hook handler instance with quality gate enabled."""
    handler = HookHandler()
    handler.config_loader.config.hooks["stop"].quality_gate = True
    return handler

@pytest.fixture
def session_id():
    """Create a test session ID."""
    return parse_session_id("12345678-1234-5678-1234-567812345678")

@pytest.fixture
def handler_basic():
    """Create a basic hook handler without quality gate."""
    return HookHandler()
```

---

## Pattern 7: Repeated Assertion Helpers (LOW PRIORITY)

### Found Helpers:

Each is unique and used in one or two places:
- `assert_worktree_exists`
- `assert_worktree_not_exists`
- `assert_output_contains`
- `assert_tool_input_parsing`
- `assert_ui_items_have`
- `assert_typed_items_have`
- `assert_payloads_have`

**Status**: No significant duplication found in assertion helpers. Each is purposeful and used appropriately.

---

## Remediation Plan (Priority Order)

### Phase 1: Immediate (High Impact)

1. **Create `claude_linter_v2/conftest.py`**
   - Extract `handler` and `session_id` fixtures
   - Provide variants for different configurations
   - Files affected: 4 test files in `claude_linter_v2/`
   - Estimated reduction: 12 lines of duplicated code

2. **Create shared fixture for git initialization**
   - Extract to common fixture
   - Reuse across `test_stop_hook_gitignore.py` and other tests
   - Files affected: 2-3 test files
   - Estimated reduction: 8-12 lines

### Phase 2: Medium Term (Moderate Impact)

3. **Extract mock factory functions**
   - Create `tests/factories.py` or similar
   - Replace duplicated mock setup code
   - Files affected: 9+ test files
   - Estimated reduction: 30+ lines

4. **Create assertion helpers module**
   - Create `tests/assertions.py`
   - Add: `assert_command_success()`, `assert_no_violations()`, `assert_single_violation()`
   - Files affected: All test files with CLI/subprocess assertions
   - Estimated reduction: 40+ lines

### Phase 3: Optional (Low Impact)

5. **Review `temp_db` and `test_config` duplicates**
   - Verify intentional differences
   - Consolidate if possible
   - Files affected: 2 locations

---

## Detailed Recommendations by Module

### Module: `claude_linter_v2/tests/`

**Action**: HIGH PRIORITY - Create conftest.py

**Current State**: 4 test files with duplicated fixtures
- `test_mcp_tools.py`
- `test_stop_hook_quality_gate.py`
- `test_stop_hook_gitignore.py`
- `test_stop_hook_fresh_scan.py`

**Solution**:

Create `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/conftest.py`:

```python
"""Shared fixtures for claude_linter_v2 tests."""

import subprocess
from pathlib import Path

from ducktape_llm_common.claude_linter_v2.hooks.handler import HookHandler
from ducktape_llm_common.claude_linter_v2.types import parse_session_id, SessionID
import pytest


@pytest.fixture
def handler():
    """Create a hook handler instance with quality gate enabled."""
    handler = HookHandler()
    handler.config_loader.config.hooks["stop"].quality_gate = True
    return handler


@pytest.fixture
def handler_basic():
    """Create a basic hook handler without quality gate."""
    return HookHandler()


@pytest.fixture
def session_id() -> SessionID:
    """Create a test session ID."""
    return parse_session_id("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True
    )
    return tmp_path
```

---

### Module: `difftree/tests/`

**Action**: ALREADY GOOD - Already has conftest.py with shared fixtures

**Status**: This module follows best practices with:
- Centralized fixture definitions
- Helper functions for test data
- Shared utilities

**Note for other modules**: Use as a reference implementation.

---

## Summary Statistics

| Category | Count | Files Affected | Lines to Remove |
|----------|-------|-----------------|-----------------|
| Duplicate fixtures | 4 | 4 | ~12 |
| Duplicate mock patterns | 5+ | 9+ | ~30 |
| Duplicate assertions | 26+ | Multiple | ~40 |
| Duplicate setup logic | 3+ | 2-3 | ~8-12 |
| Missing conftest.py | 1 | 4 | N/A |
| **Total estimated reduction** | | | **90-100 lines** |

---

## Implementation Checklist

- [ ] Create `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/conftest.py`
- [ ] Update `test_mcp_tools.py` to remove `handler` and `session_id` fixtures
- [ ] Update `test_stop_hook_quality_gate.py` to remove `handler` and `session_id` fixtures
- [ ] Update `test_stop_hook_gitignore.py` to remove `handler` and `session_id` fixtures
- [ ] Update `test_stop_hook_fresh_scan.py` to remove `handler` and `session_id` fixtures
- [ ] Create assertion helpers module (optional, Phase 2)
- [ ] Create test data factories module (optional, Phase 2)
- [ ] Review and consolidate `temp_db` fixtures (Phase 3)
- [ ] Review and consolidate `test_config` fixtures (Phase 3)
- [ ] Run full test suite to verify no regressions
- [ ] Add pre-commit hook to detect fixture duplication (optional)

---

## References

See the scan prompt for detailed patterns:
- @/home/user/ducktape/prompts/scans/duplicated-test-code.md

Related best practices:
- [Pytest Fixtures Documentation](https://docs.pytest.org/en/stable/fixture.html)
- [PyHamcrest Custom Matchers](https://github.com/hamcrest/PyHamcrest)
- [Refactoring Test Code](https://martinfowler.com/articles/refactoring-test-code.html)

---

**Scan completed**: 2025-11-19
**Next review**: After implementing Phase 1 fixes
