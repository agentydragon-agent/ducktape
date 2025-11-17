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
- Still catches the field-by-field problem while being more general

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

**For full object comparison, prefer plain `==`** - it's simpler and more obvious.

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

## Issues with Field-by-Field

- **Verbose** - 20 lines → 5 lines
- **Fragile** - Add a field? Update every test
- **Incomplete** - Easy to forget fields
- **Unclear intent** - What's the expected object?
- **Harder to read** - Scattered assertions vs clear data structure

## Detection

```bash
# Find tests with many assertions on same object
rg --type py -A20 "def test_" | rg "assert.*\[0\].*==" | head -20

# Find patterns like: assert obj.field1 == x; assert obj.field2 == y
rg --type py "assert \w+\.\w+ ==" --glob "test_*.py" -A1 | grep "assert"
```

## Fix Strategy

1. **Use `==` on whole objects** (if dataclass/Pydantic with `__eq__`)
2. **Use pytest.approx for floats** when needed
3. **Use structured comparison** (dict, list, tuple)
4. **Parametrize** for multiple test cases

## Pattern 2: Collection Assertions

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

## Pattern 3: Type Checks

```python
# BAD: Manual isinstance
assert isinstance(result, User)
assert type(obj) == MyClass

# GOOD: PyHamcrest matchers
from hamcrest import assert_that, instance_of

assert_that(result, instance_of(User))
assert_that(obj, instance_of(MyClass))
```

## Pattern 4: String Assertions

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

## Pattern 5: Numeric Comparisons

```python
# BAD: Manual numeric assertions
assert count > 0
assert value >= 10 and value <= 20
assert abs(result - 3.14) < 0.01

# GOOD: PyHamcrest matchers
from hamcrest import assert_that, greater_than, greater_than_or_equal_to, close_to

assert_that(count, greater_than(0))
assert_that(value, all_of(greater_than_or_equal_to(10), less_than_or_equal_to(20)))
assert_that(result, close_to(3.14, 0.01))
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

## When Plain Assert Is Okay

- **Simple equality on primitives**: `assert x == 5` (though `assert_that(x, equal_to(5))` is better)
- **Boolean conditions**: `assert is_valid` (though `assert_that(is_valid, is_(True))` is clearer)
- **Quick prototypes/debugging**

But for production tests, PyHamcrest matchers provide:
- **Better failure messages** ("Expected: greater than 5, but was: 3")
- **Self-documenting** (matcher name explains intent)
- **Composable** (combine matchers for complex conditions)

## Detection Strategy

```bash
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
```

## References

- [PyHamcrest Documentation](https://pyhamcrest.readthedocs.io/)
- [Effective Python Testing](https://realpython.com/pytest-python-testing/)
- [Test Clarity](https://www.satisfice.com/blog/archives/856)
