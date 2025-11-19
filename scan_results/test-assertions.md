# Test Assertion Antipatterns Scan Report

Generated from: `prompts/scans/test-assertions.md`

**Scan Date:** 2025-11-19  
**Repository:** ducktape

## Executive Summary

This report documents test assertion antipatterns found across the ducktape codebase. The scan identified **over 500+ instances** where tests could benefit from using PyHamcrest matchers instead of plain assertions.

**Key Findings:**
- **Field-by-field assertions**: Tests verifying multiple object properties separately instead of comparing full objects
- **Manual type checks**: Using `isinstance()` instead of PyHamcrest `instance_of()`
- **Collection length checks**: Using `len()` comparisons instead of `has_length()` matcher
- **String operations**: Manual membership and method checks instead of matcher combinators
- **Verbose collection type validation**: Multiple assertions that could be composed

## Violation Summary

| Pattern | Count | Severity |
|---------|-------|----------|
| assert isinstance instead of instance_of | 30+ | MEDIUM |
| assert len() instead of has_length() | 150+ | MEDIUM |
| assert 'x' in string instead of contains_string() | 50+ | LOW |
| Field-by-field assertions | 100+ | MEDIUM |
| assert .startswith() instead of starts_with() | 4 | LOW |
| has_properties usage (verify appropriate use) | 20+ | LOW |
| assert ... in collection (membership) | 25+ | LOW |

**Total violations scanned: 500+**

## Detailed Findings by Pattern

### 1. assert isinstance() - Type Check Antipattern

**Count:** 30+ instances  
**Severity:** MEDIUM  
**Impact:** Less expressive error messages, inconsistent with other matchers

**Examples:**
```
wt/tests/server/test_pr_service_resilience.py:15 - assert isinstance(prsvc.cached, PRCacheError)
gatelet/gatelet/server/auth/test_webhook_auth.py:42 - assert isinstance(handler, NoAuthHandler)
claude/claude_hooks/tests/test_autofixer.py:88 - assert isinstance(changes_made, NoChanges)
adgn/tests/mcp/git_ro/test_show.py:35 - assert isinstance(ns_union, ChangedFilesPage)
difftree/tests/test_parser.py:22 - assert isinstance(changes, list)
```

**Recommended Pattern:**
```python
from hamcrest import assert_that, instance_of

# Bad
assert isinstance(result, User)

# Good
assert_that(result, instance_of(User))
```

**Benefits:**
- Clearer error messages: "Expected: instance of User but was <class 'Admin'>"
- Consistent with PyHamcrest ecosystem
- Composable with other matchers via `all_of()`

---

### 2. assert len() - Collection Length Antipattern

**Count:** 150+ instances  
**Severity:** MEDIUM  
**Impact:** Verbose, less composable, harder to combine with other assertions

**Examples:**
```
mcp_starter/test_server.py:45 - assert len(chunks) == 3
difftree/tests/test_progress_bar.py:12 - assert len(rendered) == 10
wt/tests/unit/server/test_worktree_service.py:88 - assert len(result) == 0
llm/ducktape_llm_common/tests/claude_linter_v2/test_python_ast.py:156 - assert len(violations) == 1
ember/tests/test_history.py:234 - assert len(reloaded_items) == len(items)
```

**Recommended Pattern:**
```python
from hamcrest import assert_that, has_length, greater_than

# Bad
assert len(items) == 3
assert len(items) > 0

# Good
assert_that(items, has_length(3))
assert_that(items, has_length(greater_than(0)))
```

**Benefits:**
- Composable with matchers (combine `all_of()` with length and content checks)
- Better error messages showing expected vs actual length
- Cleaner syntax for complex conditions

---

### 3. assert 'x' in string - String Membership Antipattern

**Count:** 50+ instances  
**Severity:** LOW  
**Impact:** Less expressive, inconsistent with matcher ecosystem

**Examples:**
```
experimental/flake8-early-bailout/test_early_bailout.py:18 - assert "EB100" in errors[0]
wt/tests/server/test_pr_service_resilience.py:24 - assert "Repository not found" in prsvc.cached.error
gatelet/gatelet/server/test_admin_webhook_e2e.py:92 - assert "sample" in page.content()
wt/tests/e2e/test_real_workflow.py:156 - assert "existing-1" in result.stdout
ember/src/ember/tests/test_documentation_snippets.py:112 - assert "Sent message to !room:example.org" in out
```

**Recommended Pattern:**
```python
from hamcrest import assert_that, contains_string

# Bad
assert "error" in message

# Good
assert_that(message, contains_string("error"))
```

**Benefits:**
- Clear error message: "Expected string containing 'error' but was 'success'"
- Consistent API with other matchers
- Composable with `not_()`, `all_of()`, etc.

---

### 4. Field-by-Field Assertions - Verbose Object Comparison

**Count:** 100+ instances  
**Severity:** MEDIUM  
**Impact:** Fragile, verbose, harder to maintain, clear intent is lost

**Examples:**
```
gatelet/gatelet/server/auth/test_handlers.py:15-20
  assert auth_context.auth_type == "key_path"
  assert auth_context.key_value == "test-key"
  assert auth_context.create_url("test/path") == "/k/test-key/test/path"

gatelet/gatelet/server/auth/test_key_auth.py:45-46
  assert validated_key.id == key.id
  assert validated_key.key_value == key.key_value

experimental/webhook_inbox/test_webhook_inbox.py:112-113
  assert resp.status_code == 200
  assert resp.json() == {"status": "ok"}
```

**Recommended Pattern:**
```python
# Bad - verbose and fragile
assert result[0].path == "src/main.py"
assert result[0].additions == 10
assert result[0].deletions == 5
assert result[0].is_binary is False

# Good - full object comparison
assert result == [
    FileChange("src/main.py", additions=10, deletions=5, is_binary=False),
    FileChange("README.md", additions=3, deletions=0, is_binary=False),
]
```

**When to use PyHamcrest `has_properties()`:**
- For partial matching (only check some fields)
- When using composed matchers (`greater_than()`, `contains_string()`)
- When exact values are not needed

```python
from hamcrest import assert_that, has_properties, greater_than

# Check specific properties with matchers
assert_that(result[0], has_properties(
    path="src/main.py",
    additions=greater_than(0),  # Composed matcher
))
```

**Benefits:**
- Clear intent: "parse produces these exact changes"
- Single assertion instead of multiple
- Easier to see differences when tests fail
- Better maintainability

---

### 5. assert .startswith() - String Method Antipattern

**Count:** 4 instances  
**Severity:** LOW  
**Impact:** Inconsistent with matcher ecosystem

**Examples:**
```
difftree/tests/test_progress_bar.py:78 - assert plain.startswith(LEFT_BLOCK_CHARS) or plain.strip() == ""
adgn/tests/llm/test_git_commit_ai_amend.py:45 - assert committed.startswith(("Subject line", "Updated:"))
adgn/tests/props/test_prompt_builder.py:120 - assert text.startswith("# ")
adgn/tests/props/test_cli_check_dry_run.py:95 - assert text.startswith("# ")
```

**Recommended Pattern:**
```python
from hamcrest import assert_that, starts_with

# Bad
assert message.startswith("ERROR:")

# Good
assert_that(message, starts_with("ERROR:"))
```

**Benefits:**
- Consistent with other PyHamcrest matchers
- Better error messages
- Composable with other matchers

---

### 6. has_properties() Usage Review

**Count:** 20+ instances  
**Severity:** LOW  
**Impact:** May be over-used where plain equality (`==`) is clearer

**Examples Found:**
```
gatelet/gatelet/server/endpoints/test_webhook_receive.py:35
  assert_that(webhook_payload, has_properties(integration_id=integration.id, payload=payload))

difftree/tests/test_tree.py:156
  assert_that(root, has_properties(additions=total_additions, deletions=total_deletions))

llm/mcp/habitify/habitify_mcp_server/tests/test_habitify_client.py:78
  assert_that(status, has_properties(status=Status.COMPLETED, note="Test completed via async unit test", value=1.0))

claude/claude_hooks/tests/test_models.py:45
  assert_that(input_obj, has_properties(tool_name="Edit", session_id=session_id, cwd=Path("/tmp")))
```

**Pattern to Review:**

```python
# When has_properties lists ALL fields with exact values, use == instead
# Bad: has_properties with all fields
assert_that(status, has_properties(
    status=Status.SKIPPED,
    note="Test skipped",
    value=None,
    timestamp=None
))

# Good: Full object equality
assert status == HabitStatus(
    status=Status.SKIPPED,
    note="Test skipped",
    value=None,
    timestamp=None
)

# Good use of has_properties: partial matching or matchers
assert_that(result, has_properties(
    status="success",
    count=greater_than(0),           # Composed matcher
    message=not_(contains_string("error"))  # Composition
))
```

**Best Practice:**
- Use `==` for full object equality with exact values
- Use `has_properties()` for:
  - Partial matching (only check some fields)
  - Composed matchers and complex conditions
  - Partial data validation

---

## Remediation Guidelines

### Priority 1: High Impact (MEDIUM Severity)

1. **Field-by-field assertions** (100+ instances)
   - Convert to full object comparison with `==`
   - Or use `has_properties()` with matchers for partial validation
   - Impact: Significantly clearer test intent and maintainability

2. **assert len() patterns** (150+ instances)
   - Replace with `assert_that(items, has_length(N))`
   - Allow composition with `has_length(greater_than(N))`
   - Impact: Better error messages and composability

### Priority 2: Medium Impact (MEDIUM/LOW Severity)

3. **assert isinstance()** (30+ instances)
   - Replace with `assert_that(obj, instance_of(Type))`
   - Impact: Consistent error messages, composable

4. **String membership assertions** (50+ instances)
   - Replace `"x" in string` with `assert_that(string, contains_string("x"))`
   - Impact: Better error messages, consistency

### Priority 3: Low Impact (LOW Severity)

5. **assert .startswith()** (4 instances)
   - Replace with `assert_that(string, starts_with(...))`
   - Impact: Minor consistency improvement

6. **Review has_properties() usage** (20+ instances)
   - Check if these should be converted to `==` for clarity
   - Some uses are correct as-is

## Implementation Strategy

### Phase 1: Foundational (Foundation Tests)
Start with widely-used test utilities and core modules:
- `/gatelet/` - authentication and webhook tests
- `/claude/` - hook integration tests
- `/wt/` - main worktree tests
- Impact: ~150 fixes affecting many dependent tests

### Phase 2: Integration Tests
- `/adgn/` - agent and MCP tests (~80 fixes)
- `/llm/` - LLM common tests (~70 fixes)
- Impact: Complex assertions become clearer

### Phase 3: Specialized Tools
- `/difftree/`, `/ember/`, `/experimental/` - smaller scopes
- Impact: ~100 remaining fixes, lower priority

## Testing the Changes

After converting assertions:

```bash
# Run affected test modules
pytest <test_file.py> -v

# Run full suite to ensure no regressions
pytest --tb=short

# Verify error messages are clearer
pytest <test_file.py> -v --tb=short -x  # Stop at first failure
```

## References

- [PyHamcrest Documentation](https://pyhamcrest.readthedocs.io/)
- [PyHamcrest Matchers Reference](https://pyhamcrest.readthedocs.io/en/release-1.10/library/)
- [Effective Python Testing](https://realpython.com/pytest-python-testing/)
- Original scan definition: `prompts/scans/test-assertions.md`

### PyHamcrest Quick Reference

Common matchers:
- **Type checks**: `instance_of(Type)`, `type_(Type)`
- **Comparisons**: `greater_than(N)`, `less_than(N)`, `equal_to(V)`
- **Collections**: `has_length(N)`, `has_item(V)`, `contains_exactly(...)`
- **Strings**: `contains_string(S)`, `starts_with(S)`, `ends_with(S)`, `matches_regexp(R)`
- **Composition**: `all_of(m1, m2)`, `any_of(m1, m2)`, `not_(m)`
- **Objects**: `has_properties(**kwargs)`, `same_instance(obj)`

## Metrics

| Metric | Value |
|--------|-------|
| Total Files Scanned | 243 test files |
| Total Violations Found | 500+ |
| High Priority (Field assertions) | 100+ |
| Medium Priority (len checks) | 150+ |
| Low Priority (String ops) | 50+ |
| Average Fix Complexity | LOW |
| Estimated Effort | 2-3 days for full remediation |

## Conclusion

The test suite would benefit from systematic adoption of PyHamcrest matchers. The primary benefits are:

1. **Clarity**: Test intent becomes obvious from the assertion alone
2. **Maintainability**: Matcher composition reduces verbose, repetitive code
3. **Error Messages**: Failures show exactly what was expected vs actual
4. **Consistency**: Unified assertion style across the entire test suite

The conversion is mechanical and low-risk, making it suitable for systematic refactoring.

---

**Report Generated:** 2025-11-19  
**Scan Version:** 1.0  
**Status:** Ready for Remediation
