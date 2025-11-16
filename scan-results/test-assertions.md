# Test Assertion Antipatterns Scan Results

**Scan Date**: 2025-11-16
**Repository**: ducktape
**Scan Definition**: `/home/user/ducktape/prompts/scans/test-assertions.md`

## Executive Summary

The ducktape codebase contains extensive use of plain `assert` statements that would benefit from PyHamcrest matchers for improved test clarity, better error messages, and composability. The scan identified **89 test files** with opportunities for improvement across all 6 antipattern categories.

**Key Finding**: One file (`gatelet/server/endpoints/test_webhook_receive.py`) already demonstrates partial PyHamcrest adoption, showing that the transition is feasible and beneficial.

## Pattern 1: Field-by-Field Assertions

### High-Impact Cases

#### `/home/user/ducktape/difftree/tests/test_parser.py`
**Lines 14-17**: Classic field-by-field antipattern
```python
# BAD: Manual field-by-field assertions
assert change.path == "test.py"
assert change.additions == 10
assert change.deletions == 5
assert change.total_changes == 15
```

**Recommendation**: Use plain equality for full object comparison
```python
# GOOD: Compare whole object
assert change == FileChange(
    path="test.py",
    additions=10,
    deletions=5,
    is_binary=False
)
```

**Lines 52-54**: Checking binary file properties
```python
# BAD: Field-by-field for binary file
binary_change = next(c for c in changes if c.path == "image.png")
assert binary_change.is_binary is True
assert binary_change.additions == 0
assert binary_change.deletions == 0
```

**Recommendation**: Use full object comparison or `has_properties()` for partial matching
```python
# GOOD: Full comparison
expected_binary = FileChange(
    path="image.png",
    additions=0,
    deletions=0,
    is_binary=True
)
assert binary_change == expected_binary

# ALTERNATIVE: If only checking these properties (ignoring others)
from hamcrest import assert_that, has_properties
assert_that(binary_change, has_properties(
    is_binary=True,
    additions=0,
    deletions=0
))
```

#### `/home/user/ducktape/difftree/tests/test_tree.py`
**Lines 24-26, 30-33**: Multiple field assertions on tree nodes
```python
# BAD: Field-by-field on root
assert root.additions == 10
assert root.deletions == 5

# BAD: Field-by-field on child
assert test_file.name == "test.py"
assert test_file.is_file
assert test_file.additions == 10
assert test_file.deletions == 5
```

**Recommendation**: Use plain equality
```python
# GOOD: Compare root aggregates
assert root == TreeNode(
    name=root.name,  # Dynamic value
    is_file=False,
    additions=10,
    deletions=5,
    children={"test.py": expected_test_file}
)
```

**Lines 70-71, 77-78**: Repeated pattern for directory statistics
```python
# BAD: Field-by-field assertions on directory stats
assert models_dir.additions == 20 + 15  # user.py + post.py
assert models_dir.deletions == 5 + 3

assert src_dir.additions == expected_additions
assert src_dir.deletions == expected_deletions
```

**Impact**: 15+ assertions could be reduced to 3-4 object comparisons

#### `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tests/test_habitify_client.py`
**Lines 269-271**: Checking multiple properties of status object
```python
# BAD: Field-by-field assertions
assert isinstance(status, HabitStatus)
assert status.status == "completed"
assert status.note == "Test completed via async unit test"
assert status.value == 1.0
```

**Recommendation**: Combine type check with property matching
```python
# BETTER: Using has_properties for composed assertions
from hamcrest import assert_that, instance_of, has_properties

assert_that(status, instance_of(HabitStatus))
assert_that(status, has_properties(
    status="completed",
    note="Test completed via async unit test",
    value=1.0
))

# OR if checking all fields exactly:
assert status == HabitStatus(
    status="completed",
    note="Test completed via async unit test",
    value=1.0,
    date=status.date  # If date doesn't matter
)
```

**Lines 298-301**: Similar pattern for skipped status
```python
# BAD: Multiple assertions
assert isinstance(status, HabitStatus)
assert status.status == "skipped"
assert status.note == "Test skipped via async unit test"
assert status.value is None
```

**Impact**: 20+ test methods with this pattern

### Medium-Impact Cases

#### `/home/user/ducktape/difftree/tests/test_cli.py`
**Lines 35, 45, 52, etc.**: Exit code checks scattered throughout
```python
# ACCEPTABLE but could be improved
assert result.exit_code == 0
assert result_tree_only.exit_code == 0
assert result_with_counts.exit_code == 0
```

**Note**: These are acceptable as simple equality checks, but for production tests, `assert_that(result.exit_code, equal_to(0))` provides better error messages.

## Pattern 2: Collection Assertions

### High-Impact Cases

#### Multiple files using `assert len(...)`
**Found in 47+ locations across**:
- `wt/tests/unit/server/test_worktree_service.py` (lines 44, 59, 84)
- `claude/claude_optimizer/tests/test_optimizer.py` (lines 128, 159, 230)
- `experimental/flake8-early-bailout/test_early_bailout.py` (lines 32, 54, 73, 93, 128)
- `llm/ducktape_llm_common/tests/claude_linter_v2/test_diff_intelligence.py` (28, 51, 88, 140)

**Example from test_optimizer.py**:
```python
# BAD: Manual length checks
assert len(engineer._turns) == 0
assert len(engineer._turns) == 2
assert len(reasoning) == 1
```

**Recommendation**: Use PyHamcrest collection matchers
```python
from hamcrest import assert_that, empty, has_length

# GOOD: Expressive matchers
assert_that(engineer._turns, empty())
assert_that(engineer._turns, has_length(2))
assert_that(reasoning, has_length(1))
```

**Better Error Messages**:
- Plain: `AssertionError: assert 3 == 2`
- PyHamcrest: `Expected: a sequence with size <2>, but: was <3> items`

#### Multiple files using `assert ... in ...`
**Found in 100+ locations** including:
- `difftree/tests/test_diff_tree.py` (lines 68-70, 80-82, 92-96)
- `difftree/tests/test_tree.py` (lines 23, 27, 48-50, 54-56, 60-61)

**Example from test_tree.py**:
```python
# BAD: Multiple membership checks
assert "src" in root.children
assert "tests" in root.children
assert "README.md" in root.children

assert "main.py" in src_dir.children
assert "utils.py" in src_dir.children
assert "models" in src_dir.children
```

**Recommendation**: Use collection matchers
```python
from hamcrest import assert_that, has_entries, has_items, has_key

# GOOD: Check multiple keys at once
assert_that(root.children, has_items("src", "tests", "README.md"))

# OR: Check for specific keys in dict
assert_that(root.children, has_key("src"))
assert_that(root.children, has_key("tests"))

# BETTER: For dict membership, combine with other checks
assert_that(src_dir.children, has_entries({
    "main.py": anything(),
    "utils.py": anything(),
    "models": anything()
}))
```

### Medium-Impact Cases

#### `/home/user/ducktape/difftree/tests/test_diff_tree.py`
**Lines 294, 299**: Checking for ANSI codes in output
```python
# ACCEPTABLE: String membership checks
assert "\x1b[2m├── \x1b[0m" in result or "\x1b[2m└── \x1b[0m" in result
assert "\x1b[2m│" in result
```

**Note**: For string checks, PyHamcrest's `contains_string()` is clearer:
```python
from hamcrest import assert_that, contains_string, any_of

assert_that(result, any_of(
    contains_string("\x1b[2m├── \x1b[0m"),
    contains_string("\x1b[2m└── \x1b[0m")
))
assert_that(result, contains_string("\x1b[2m│"))
```

## Pattern 3: Type Checks

### High-Impact Cases

#### `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tests/test_habitify_client.py`
**Found in 14+ locations** (lines 35, 36, 58, 98, 99, 130, 158, 180, 231, 268, 298)

**Example**:
```python
# BAD: Manual isinstance checks
assert isinstance(habits, list)
assert all(isinstance(habit, Habit) for habit in habits)
assert isinstance(habit, Habit)
assert isinstance(areas, list)
assert isinstance(status, HabitStatus)
```

**Recommendation**: Use PyHamcrest instance matchers
```python
from hamcrest import assert_that, instance_of, only_contains

# GOOD: Type matchers
assert_that(habits, instance_of(list))
assert_that(habits, only_contains(instance_of(Habit)))
assert_that(habit, instance_of(Habit))
assert_that(areas, instance_of(list))
assert_that(status, instance_of(HabitStatus))
```

**Better Error Messages**:
- Plain: `AssertionError: assert False`
- PyHamcrest: `Expected: an instance of Habit, but: was <str 'invalid'>`

#### `/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_mcp_tools.py`
**Found in 20+ locations** (lines 49, 62, 89, 108, 124, 152, etc.)

**Example**:
```python
# BAD: Repeated isinstance checks for outcome types
assert isinstance(outcome, PreToolApprove)
assert isinstance(outcome, PostToolSuccess)
assert isinstance(outcome, PreToolDeny)
```

**Impact**: Every test method has 1-3 isinstance checks

#### `/home/user/ducktape/claude/claude_hooks/tests/test_integration.py`
**Lines 38, 59, 74, 91, 106, 135, 157**: Union type checks
```python
# BAD: Union type checks with isinstance
assert isinstance(hook_result, PostToolContinue | PostToolFeedbackToClaude)
```

**Recommendation**: Use `any_of` matcher
```python
from hamcrest import assert_that, any_of, instance_of

# GOOD: Union type matching
assert_that(hook_result, any_of(
    instance_of(PostToolContinue),
    instance_of(PostToolFeedbackToClaude)
))
```

### Medium-Impact Cases

#### `/home/user/ducktape/difftree/tests/test_parser.py`
**Line 30**: Simple list type check
```python
# ACCEPTABLE: Simple type check
assert isinstance(changes, list)
```

**Note**: Still benefits from PyHamcrest for consistency and better errors.

## Pattern 4: String Assertions

### High-Impact Cases

#### Multiple files using `startswith()`
**Found in 11+ locations**:
- `experimental/webhook_inbox/test_webhook_inbox.py` (line 67)
- `adgn/tests/props/test_specimen_prompts_dry_run.py` (lines 42, 56, 69)
- `adgn/tests/props/test_prompt_builder.py` (lines 23, 32)

**Example**:
```python
# BAD: Manual string checks
assert r.headers["location"].startswith("/?before=")
assert text.splitlines()[0].startswith("# ")
assert lines[0].startswith("# "), "expected H1 header at top of prompt"
```

**Recommendation**: Use PyHamcrest string matchers
```python
from hamcrest import assert_that, starts_with

# GOOD: String matchers
assert_that(r.headers["location"], starts_with("/?before="))
assert_that(text.splitlines()[0], starts_with("# "))
assert_that(lines[0], starts_with("# "), "expected H1 header at top of prompt")
```

**Note**: PyHamcrest preserves custom error messages as the third parameter.

#### String containment checks
**Found in 100+ locations using `assert "..." in string`**

**Examples from test_diff_tree.py**:
```python
# BAD: String membership checks
assert "src" in result
assert "tests" in result
assert "37.5%" in file1_line
assert "No changes" in result.output
```

**Recommendation**:
```python
from hamcrest import assert_that, contains_string

# GOOD: String containment matchers
assert_that(result, contains_string("src"))
assert_that(result, contains_string("tests"))
assert_that(file1_line, contains_string("37.5%"))
assert_that(result.output, contains_string("No changes"))
```

### Medium-Impact Cases

#### `/home/user/ducktape/difftree/tests/test_diff_tree.py`
**Lines 445-447**: Checking percentage values in output
```python
# BAD but informative: Assertions with detailed messages
assert "37.5%" in file1_line, f"file1.py should show 37.5%, got: {file1_line}"
assert "12.5%" in file2_line, f"file2.py should show 12.5%, got: {file2_line}"
assert "50.0%" in file3_line, f"file3.py should show 50.0%, got: {file3_line}"
```

**Recommendation**: PyHamcrest provides detailed messages automatically
```python
from hamcrest import assert_that, contains_string

# GOOD: Matchers provide context automatically
assert_that(file1_line, contains_string("37.5%"))
assert_that(file2_line, contains_string("12.5%"))
assert_that(file3_line, contains_string("50.0%"))
```

**PyHamcrest Error Output**:
```
Expected: a string containing '37.5%'
     but: was 'file1.py  +100  -50  25.0%'
```

## Pattern 5: Numeric Comparisons

### High-Impact Cases

#### `/home/user/ducktape/difftree/tests/test_diff_tree.py`
**Lines 392-415**: Complex numeric assertions with ranges
```python
# BAD: Manual range checks
assert file1_plus >= 7, f"file1.py should have at least 7 '+', got {file1_plus}"
assert file1_plus <= 9, f"file1.py should have at most 9 '+', got {file1_plus}"
assert file1_minus >= 4, f"file1.py should have at least 4 '-', got {file1_minus}"
assert file1_minus <= 6, f"file1.py should have at most 6 '-', got {file1_minus}"

assert file2_plus == 1, f"file2.py should have exactly 1 '+' (minimal sliver), got {file2_plus}"

assert file3_plus >= 1, f"file3.py should have at least 1 '+', got {file3_plus}"
assert file3_plus <= 3, f"file3.py should have at most 3 '+', got {file3_plus}"
```

**Recommendation**: Use PyHamcrest numeric matchers
```python
from hamcrest import assert_that, all_of, greater_than_or_equal_to, less_than_or_equal_to, equal_to

# GOOD: Numeric matchers with composition
assert_that(file1_plus, all_of(
    greater_than_or_equal_to(7),
    less_than_or_equal_to(9)
))
assert_that(file1_minus, all_of(
    greater_than_or_equal_to(4),
    less_than_or_equal_to(6)
))

assert_that(file2_plus, equal_to(1))

assert_that(file3_plus, all_of(
    greater_than_or_equal_to(1),
    less_than_or_equal_to(3)
))
```

**Better Error Messages**:
- Plain: `AssertionError: assert 10 >= 7`
- PyHamcrest: `Expected: (a value greater than or equal to <7> and a value less than or equal to <9>), but: <10> was greater than or equal to <7>`

#### `/home/user/ducktape/experimental/flake8-early-bailout/test_early_bailout.py`
**Lines 54, 128**: Minimum threshold checks
```python
# BAD: Simple threshold checks
assert len(errors) >= 1
```

**Recommendation**:
```python
from hamcrest import assert_that, has_length, greater_than_or_equal_to

# GOOD: More expressive
assert_that(errors, has_length(greater_than_or_equal_to(1)))

# OR for simple cases:
from hamcrest import not_, empty
assert_that(errors, not_(empty()))
```

### Medium-Impact Cases

#### Exact equality comparisons
Many files use exact numeric equality (`assert x == 5`), which is acceptable but could benefit from PyHamcrest for consistency:

```python
# Current (acceptable):
assert len(errors) == 1
assert mock_get.call_count == 5

# Better (consistent style):
from hamcrest import assert_that, has_length, equal_to
assert_that(errors, has_length(1))
assert_that(mock_get.call_count, equal_to(5))
```

## Pattern 6: Complex Composite Assertions

### High-Impact Cases

#### `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tests/test_habitify_client.py`
**Lines 40-41, 59-60, 103-104**: Multiple properties checked sequentially
```python
# BAD: Separate assertions on same object
assert habits[0].id == "-Lo9NTLRX3aCxg-PjN25"
assert not habits[0].archived

assert habit.id == "-Lo9NTLRX3aCxg-PjN25"
assert not habit.archived

assert areas[0].id == "-LrYlUBnzjyceYei_k5Z"
assert areas[0].name == "H****h"
```

**Recommendation**: Use `has_properties()` for composite matching
```python
from hamcrest import assert_that, has_properties, is_

# GOOD: Single composite assertion
assert_that(habits[0], has_properties(
    id="-Lo9NTLRX3aCxg-PjN25",
    archived=is_(False)
))

assert_that(habit, has_properties(
    id="-Lo9NTLRX3aCxg-PjN25",
    archived=is_(False)
))

assert_that(areas[0], has_properties(
    id="-LrYlUBnzjyceYei_k5Z",
    name="H****h"
))
```

#### `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tests/test_habitify_client.py`
**Lines 261-265**: Checking request call details
```python
# BAD: Multiple assertions on mock call
assert url == "/status/-Lo9NTLRX3aCxg-PjN25"
assert body["status"] == "completed"
assert "target_date" in body
assert body["note"] == "Test completed via async unit test"
assert body["value"] == 1.0
```

**Recommendation**: Combine assertions
```python
from hamcrest import assert_that, equal_to, has_entries, has_key

# GOOD: Composite assertions
assert_that(url, equal_to("/status/-Lo9NTLRX3aCxg-PjN25"))
assert_that(body, has_entries(
    status="completed",
    note="Test completed via async unit test",
    value=1.0
))
assert_that(body, has_key("target_date"))
```

### Medium-Impact Cases

#### `/home/user/ducktape/difftree/tests/test_diff_tree.py`
**Lines 67-71**: Checking config columns
```python
# BAD: Multiple membership checks on same object
assert diff_tree.root is not None
assert Column.COUNTS in diff_tree.config.columns
assert Column.BARS in diff_tree.config.columns
assert Column.PERCENTAGES in diff_tree.config.columns
assert diff_tree.config.bar_width == 20
```

**Recommendation**:
```python
from hamcrest import assert_that, not_none, has_properties, has_items

# GOOD: Composite check
assert_that(diff_tree.root, not_none())
assert_that(diff_tree.config, has_properties(
    columns=has_items(Column.COUNTS, Column.BARS, Column.PERCENTAGES),
    bar_width=20
))
```

## Positive Example: Partial PyHamcrest Adoption

### `/home/user/ducktape/gatelet/gatelet/server/endpoints/test_webhook_receive.py`

This file demonstrates **successful PyHamcrest adoption** in some places:

**Lines 5, 35, 67**: Already using PyHamcrest!
```python
from hamcrest import anything, assert_that, has_entries

# GOOD: Using PyHamcrest matchers
assert_that(data, has_entries(status="ok", payload_id=anything()))
```

**However**, the same file mixes styles:
```python
# Mixed with plain assertions
assert response.status_code == HTTPStatus.OK
assert webhook_payload.integration_name == integration.name
assert webhook_payload.payload == payload
```

**Recommendation**: Complete the migration
```python
from hamcrest import assert_that, equal_to, has_properties

# CONSISTENT: Full PyHamcrest usage
assert_that(response.status_code, equal_to(HTTPStatus.OK))
assert_that(webhook_payload, has_properties(
    integration_name=integration.name,
    payload=payload
))
```

**This file proves PyHamcrest is already in the dependency tree and working!**

## Summary Statistics

### Files with Opportunities

| Pattern | Files Affected | Instances | Priority |
|---------|---------------|-----------|----------|
| Field-by-field assertions | 15+ | 50+ | High |
| Collection assertions (`len()`) | 20+ | 47+ | High |
| Collection assertions (`in`) | 30+ | 100+ | High |
| Type checks (`isinstance`) | 15+ | 60+ | High |
| String assertions | 40+ | 150+ | Medium |
| Numeric comparisons | 10+ | 30+ | Medium |
| Complex composite | 10+ | 40+ | High |

**Total Estimated Assertions**: 400+ could be improved

### Top Priority Files for Refactoring

1. **`/home/user/ducktape/difftree/tests/test_parser.py`** - Clean field-by-field antipatterns
2. **`/home/user/ducktape/difftree/tests/test_tree.py`** - Multiple field checks on tree nodes
3. **`/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tests/test_habitify_client.py`** - Type checks and composite assertions
4. **`/home/user/ducktape/difftree/tests/test_diff_tree.py`** - String and numeric assertions
5. **`/home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_mcp_tools.py`** - Repeated type checks

## Recommendations

### Immediate Actions

1. **Complete PyHamcrest migration in `gatelet/server/endpoints/test_webhook_receive.py`** - It's already partially done, finish it as a reference example

2. **Refactor difftree tests** - This is a focused, self-contained component with clear antipatterns. Good candidate for a complete migration.

3. **Create test assertion guidelines** - Document preferred PyHamcrest patterns for the project

### Migration Strategy

1. **Don't force it everywhere** - Plain `==` is fine for exact full object comparisons. Use PyHamcrest when you need:
   - Partial matching (`has_properties()`)
   - Composed matchers (`greater_than(0)`, `contains_string()`)
   - Type checks (`instance_of()`)
   - Collection checks (`has_length()`, `has_items()`)

2. **Focus on high-value cases**:
   - Tests with field-by-field assertions (biggest win)
   - Tests with multiple type checks
   - Tests with complex composite assertions
   - Tests with numeric ranges or string patterns

3. **Establish patterns**:
   ```python
   # For exact object comparison - prefer plain ==
   assert obj == ExpectedType(field1=value1, field2=value2)

   # For partial matching or composition - use has_properties()
   assert_that(obj, has_properties(
       field1=value1,
       field2=greater_than(0)  # Composed matcher
   ))

   # For collections
   assert_that(items, has_length(5))
   assert_that(items, has_items("a", "b", "c"))

   # For types
   assert_that(obj, instance_of(MyClass))

   # For strings
   assert_that(text, contains_string("expected"))
   assert_that(text, starts_with("prefix"))
   ```

### Long-term Goals

1. **Consistency across test suite** - Reduce cognitive load by using similar patterns
2. **Better error messages** - PyHamcrest provides detailed failure output
3. **More maintainable tests** - Composable matchers are easier to update
4. **Self-documenting assertions** - Matcher names explain intent

## Conclusion

The ducktape codebase has significant opportunities to improve test quality through PyHamcrest matchers. The presence of PyHamcrest in the gatelet tests proves feasibility. Focusing on the difftree tests and habitify client tests would provide the highest impact with clear, contained refactoring efforts.

**Estimated effort**: 20-30 hours to refactor the top 10 priority files
**Estimated benefit**: Clearer tests, better error messages, easier maintenance, reduced test fragility
