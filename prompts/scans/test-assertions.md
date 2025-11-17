# Scan: Test Assertion Antipatterns

## Context
@../shared-context.md

## Overview

Tests using plain `assert` statements miss opportunities for better error messages, expressivity, and composability that PyHamcrest matchers provide.

## Core Principle

**Use PyHamcrest matchers for better test assertions**:
- More expressive: `has_properties(status="success")` vs `assert obj.status == "success"`
- Better error messages: "Expected: object with property 'status' equal to 'success', but was 'failed'"
- Composable: Combine matchers with `all_of()`, `any_of()`, `not_()`
- Concise for complex assertions

## Pattern 1: Field-by-Field Assertions

### BAD: Manual field-by-field assertions

```python
def test_parse_numstat_output():
    numstat = "10\t5\tsrc/main.py\n3\t0\tREADME.md\n-\t-\timage.png"
    changes = parse_numstat_output(numstat)

    # BAD: Verbose, repetitive, fragile
    assert len(changes) == 3
    assert changes[0].path == "src/main.py"
    assert changes[0].additions == 10
    assert changes[0].deletions == 5
    assert changes[0].is_binary is False

    assert changes[1].path == "README.md"
    assert changes[1].additions == 3
    assert changes[1].deletions == 0

    assert changes[2].path == "image.png"
    assert changes[2].is_binary is True
    assert changes[2].additions == 0
    assert changes[2].deletions == 0
```

### GOOD: Compare whole objects (plain equality)

```python
def test_parse_numstat_output():
    numstat = "10\t5\tsrc/main.py\n3\t0\tREADME.md\n-\t-\timage.png"

    # Simple and obvious - just state what you expect
    assert parse_numstat_output(numstat) == [
        FileChange("src/main.py", additions=10, deletions=5, is_binary=False),
        FileChange("README.md", additions=3, deletions=0, is_binary=False),
        FileChange("image.png", additions=0, deletions=0, is_binary=True),
    ]
```

**Intent is clear**: Parse produces these exact changes. Simple, complete, obvious.

### BETTER: PyHamcrest for partial matching or composition

Use `has_properties()` when you need:
- **Partial matching** (only check some fields, ignore others)
- **Composed matchers** (e.g., `count=greater_than(0)`)

```python
from hamcrest import assert_that, has_properties, greater_than

def test_parse_creates_valid_change():
    result = parse_numstat_output("10\t5\tsrc/main.py")

    # Good: Check specific properties with matchers
    assert_that(result[0], has_properties(
        path="src/main.py",
        additions=greater_than(0),  # Composed matcher
        # Don't care about deletions, is_binary
    ))
```

**Rule**: When `has_properties()` lists ALL fields of a class with exact values, use plain `==` instead - it's simpler and clearer.

```python
# BAD: has_properties with all fields and exact values
assert_that(
    status,
    has_properties(
        status=Status.SKIPPED,
        note="Test skipped",
        value=None,
        timestamp=None,
        # ... all other fields
    ),
)

# GOOD: Full object equality
assert status == HabitStatus(
    status=Status.SKIPPED,
    note="Test skipped",
    value=None,
    timestamp=None,
    # ... all other fields
)
```

### Even Better: Parametrize multiple scenarios

```python
@pytest.mark.parametrize("numstat,expected", [
    ("10\t5\tfile.py", [FileChange("file.py", additions=10, deletions=5, is_binary=False)]),
    ("-\t-\timage.png", [FileChange("image.png", additions=0, deletions=0, is_binary=True)]),
    ("", []),
])
def test_parse_numstat_output(numstat, expected):
    assert parse_numstat_output(numstat) == expected
```

## Pattern 2: Verbose Collection Type Checks

### BAD: Multiple assertions about collection structure

```python
# BAD: Three separate assertions saying "non-empty list of Habit"
assert_that(habits, instance_of(list))
assert_that(habits, only_contains(instance_of(Habit)))
assert len(habits) > 0

# BAD: Two assertions about collection type
assert_that(areas, instance_of(list))
assert_that(areas, only_contains(instance_of(Area)))

# BAD: Checking specific type of collection when any collection works
assert_that(statuses, instance_of(list))
assert len(statuses) == 5
assert_that(statuses, only_contains(instance_of(HabitStatus)))
```

### GOOD: Concise composed assertions

```python
# GOOD: "non-empty collection of Habit" in one assertion
from hamcrest import assert_that, all_of, has_length, greater_than, only_contains, instance_of

assert_that(habits, all_of(
    has_length(greater_than(0)),
    only_contains(instance_of(Habit))
))

# GOOD: Just check content type, don't care if list/tuple
assert_that(areas, only_contains(instance_of(Area)))

# GOOD: "collection of exactly 5 HabitStatus"
assert_that(statuses, all_of(
    has_length(5),
    only_contains(instance_of(HabitStatus))
))
```

**Principle**: In tests, usually don't care if result is `list` vs `tuple` vs `set` - just care about the content. Don't assert `instance_of(list)` unless the specific collection type matters to the contract.

## Pattern 3: Collection Assertions

```python
# BAD: Manual assertions on collections
assert len(items) == 3
assert "foo" in items
assert items[0] == "first"

# GOOD: PyHamcrest matchers
from hamcrest import assert_that, has_length, has_item, contains_exactly

assert_that(items, has_length(3))
assert_that(items, has_item("foo"))
assert_that(items, contains_exactly("first", "second", "third"))
```

## Pattern 4: Type Checks

```python
# BAD: Manual isinstance
assert isinstance(result, User)
assert type(obj) == MyClass

# GOOD: PyHamcrest matchers (better error messages)
from hamcrest import assert_that, instance_of

assert_that(result, instance_of(User))
assert_that(obj, instance_of(MyClass))
```

## Pattern 5: String Assertions

```python
# BAD: Manual string checks
assert "error" in message
assert message.startswith("ERROR:")
assert re.match(r"^\d{3}-\d{4}$", code)

# GOOD: PyHamcrest matchers
from hamcrest import assert_that, contains_string, starts_with, matches_regexp

assert_that(message, contains_string("error"))
assert_that(message, starts_with("ERROR:"))
assert_that(code, matches_regexp(r"^\d{3}-\d{4}$"))
```

## Pattern 6: Complex Composite Assertions

```python
# BAD: Multiple separate assertions
assert result.status == "success"
assert result.count > 0
assert "error" not in result.message
assert isinstance(result.data, dict)

# GOOD: Plain equality if checking all fields with exact values
assert result == Result(
    status="success",
    count=5,
    message="All good",
    data={"key": "value"}
)

# BETTER: has_properties() for composed matchers or partial matching
from hamcrest import assert_that, has_properties, greater_than, not_, contains_string, instance_of

# When you need composition (>, <, contains, etc.)
assert_that(result, has_properties(
    status="success",
    count=greater_than(0),              # Not exact value - need matcher
    message=not_(contains_string("error")),  # Composition
    data=instance_of(dict)              # Type check, not exact value
))
```

**Rule**: Use plain `==` for exact full object comparison, `has_properties()` when you need matchers or partial matching.

## Detection Strategy

**Primary**: Manual code reading - read test files thoroughly, look for verbose patterns.

**Automated preprocessing** (high recall, manual verification required):

```bash
# Verbose collection checks (3+ lines about same collection)
rg --type py "assert_that.*instance_of\(list\)" --glob "test_*.py" -A2 | grep -E "(only_contains|len)"

# Field-by-field patterns
rg --type py "assert \w+\.\w+ ==" --glob "test_*.py" -A1 | grep "assert"

# Collection operations that have matchers
rg --type py "assert len\(" --glob "test_*.py"
rg --type py "assert .* in " --glob "test_*.py"

# Type checks
rg --type py "assert isinstance\(" --glob "test_*.py"

# String operations
rg --type py 'assert ".*" in \w+' --glob "test_*.py"
rg --type py "assert \w+\.startswith\(" --glob "test_*.py"

# Numeric comparisons
rg --type py "assert \w+ [><]=" --glob "test_*.py"

# has_properties with many fields (might be better as full ==)
rg --type py "has_properties\(" --glob "test_*.py" -A10
```

**Important**: Grep patterns find candidates for manual review. Don't trust them blindly. Read the actual code to understand context and determine if changes make sense.

## References

- [PyHamcrest Documentation](https://pyhamcrest.readthedocs.io/)
- [Effective Python Testing](https://realpython.com/pytest-python-testing/)
- [Test Clarity](https://www.satisfice.com/blog/archives/856)
