# Test Assertion Antipatterns - Scan Results

**Scan Date:** 2025-11-16
**Pattern:** Field-by-Field Assertions Instead of Object Comparison

## Summary

Found **6 test files** containing the antipattern of field-by-field assertions instead of whole object comparisons. These tests would benefit from:
- Using direct object equality (`assert obj == expected`)
- Parametrized tests for multiple scenarios
- More concise and maintainable test code

**Total instances:** 14 test functions with field-by-field assertions

## Findings by File

### 1. /home/user/ducktape/difftree/tests/test_parser.py

**Instance 1: `test_file_change_dataclass()` (lines 14-17)**
```python
assert change.path == "test.py"
assert change.additions == 10
assert change.deletions == 5
assert change.total_changes == 15
```

**Why it matches:** Four consecutive assertions checking individual fields of the `change` object. This could be replaced with a single object comparison:
```python
assert change == FileChange(path="test.py", additions=10, deletions=5)
assert change.total_changes == 15  # Property, keep separate
```

**Instance 2: `test_file_change_with_binary()` (lines 52-54)**
```python
assert binary_change.is_binary is True
assert binary_change.additions == 0
assert binary_change.deletions == 0
```

**Why it matches:** Three assertions on the same `binary_change` object checking individual fields instead of comparing the whole object.

---

### 2. /home/user/ducktape/difftree/tests/test_tree.py

**Instance 1: `test_build_tree_single_file()` (lines 25-26)**
```python
assert root.additions == 10
assert root.deletions == 5
```

**Why it matches:** Two assertions on the `root` object's fields.

**Instance 2: `test_build_tree_single_file()` (lines 30, 32-33)**
```python
assert test_file.name == "test.py"
assert test_file.is_file
assert test_file.additions == 10
assert test_file.deletions == 5
```

**Why it matches:** Four assertions checking individual fields of `test_file` object. Could be replaced with object comparison or tuple unpacking.

**Instance 3: `test_build_tree_nested_files()` (lines 44-45)**
```python
assert root.additions == total_additions
assert root.deletions == total_deletions
```

**Why it matches:** Two assertions on the same object. Could use tuple comparison: `assert (root.additions, root.deletions) == (total_additions, total_deletions)`

**Instance 4: `test_tree_statistics_aggregation()` (lines 70-71)**
```python
assert models_dir.additions == 20 + 15  # user.py + post.py
assert models_dir.deletions == 5 + 3
```

**Why it matches:** Two field-by-field assertions on `models_dir`.

**Instance 5: `test_tree_statistics_aggregation()` (lines 77-78)**
```python
assert src_dir.additions == expected_additions
assert src_dir.deletions == expected_deletions
```

**Why it matches:** Two field-by-field assertions on `src_dir`. Could use tuple comparison.

---

### 3. /home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tests/test_habitify_client.py

**Instance 1: `test_get_habits()` (lines 40-41)**
```python
assert habits[0].id == "-Lo9NTLRX3aCxg-PjN25"
assert not habits[0].archived
```

**Why it matches:** Two assertions checking fields on the same `habits[0]` object. Could be consolidated.

**Instance 2: `test_get_areas()` (lines 103-104)**
```python
assert areas[0].id == "-LrYlUBnzjyceYei_k5Z"
assert areas[0].name == "H****h"
```

**Why it matches:** Two field-by-field assertions on `areas[0]`. Could compare the whole object or use tuple comparison.

---

### 4. /home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_diff_intelligence.py

**Instance 1: `test_categorize_in_diff()` (lines 89-91)**
```python
assert categorized[0].category == "in-diff"
assert categorized[0].distance_from_change == 0
assert categorized[1].category == "out-of-diff"
```

**Why it matches:** Multiple field assertions on list items. While checking different indices, the pattern of field-by-field checking for `categorized[0]` (2 fields) matches the antipattern.

**Instance 2: `test_categorize_near_diff()` (lines 110-114)**
```python
assert categorized[0].category == "near-diff"
assert categorized[0].distance_from_change == 2
assert categorized[1].category == "near-diff"
assert categorized[1].distance_from_change == 3
assert categorized[2].category == "out-of-diff"
```

**Why it matches:** Five assertions checking fields across multiple list items. Each item has 2 field checks. Could use list comparison with expected objects.

**Instance 3: `test_filter_by_priority()` (lines 141-142)**
```python
assert filtered[0].category == "in-diff"
assert filtered[1].category == "near-diff"
```

**Why it matches:** Field-by-field assertions on list items. While only checking one field per item, this pattern could benefit from list comparison.

---

### 5. /home/user/ducktape/llm/ducktape_llm_common/tests/claude_linter_v2/test_python_ast.py

**Instance 1: `test_detects_bare_except()` (lines 21-23)**
```python
assert violations[0].line == 4
assert "bare except" in violations[0].message.lower()
assert violations[0].rule == "bare_except"
```

**Why it matches:** Three assertions checking fields on `violations[0]`. Could extract fields into a tuple or use object comparison for the first and last assertions.

**Instance 2: `test_detects_hasattr()` (lines 68-70)**
```python
assert violations[0].line == 3
assert "hasattr" in violations[0].message
assert violations[0].rule == "getattr_setattr"
```

**Why it matches:** Three field-by-field assertions on `violations[0]`.

---

### 6. /home/user/ducktape/claude/claude_optimizer/tests/test_full_e2e_workflow.py

**Instance 1: `test_full_e2e_workflow()` (lines 679-680)**
```python
assert prompts[0].iteration == 0
assert prompts[1].iteration == 1
```

**Why it matches:** Field assertions on different list items. While checking different objects, this is a repetitive pattern that could be replaced with list comprehension or parametrized comparison.

**Instance 2: `test_full_e2e_workflow()` (lines 710-711)**
```python
assert "broad exception handling" in analyses[0].summary_text
assert analyses[0].input_rollout_count == 2
```

**Why it matches:** Two field assertions on the same `analyses[0]` object.

---

## Recommendations

### High Priority (Most Verbose)
1. **difftree/tests/test_parser.py**: `test_file_change_dataclass()` - 4 field assertions
2. **difftree/tests/test_tree.py**: `test_build_tree_single_file()` - 4 field assertions on test_file
3. **test_diff_intelligence.py**: `test_categorize_near_diff()` - 5 assertions across multiple items

### Medium Priority
- All instances with 2-3 field assertions could benefit from tuple comparison or object equality
- Consider parametrization for tests with similar patterns across multiple objects

### Refactoring Approach

**For dataclasses/Pydantic models** (already have `__eq__`):
```python
# Before
assert obj.field1 == value1
assert obj.field2 == value2

# After
assert obj == ExpectedClass(field1=value1, field2=value2)
```

**For simple field groups**:
```python
# Before
assert obj.additions == 10
assert obj.deletions == 5

# After
assert (obj.additions, obj.deletions) == (10, 5)
```

**For list items**:
```python
# Before
assert items[0].field == value1
assert items[1].field == value2

# After
assert [item.field for item in items] == [value1, value2]
```

## Impact

Refactoring these tests would:
- **Reduce test code by ~30-50%** (estimated 60+ lines → 30-35 lines)
- **Improve maintainability**: Adding fields requires updating one place, not scattered assertions
- **Clarify intent**: The expected object is clearly stated upfront
- **Reduce fragility**: Less likely to forget asserting new fields
