# Habitify MCP Server - Refactoring Plan

## Overview

This document outlines opportunities for refactoring and improvements in the Habitify MCP Server codebase.

## High Priority Refactoring

### 1. **Eliminate Test Code Duplication (333 lines, ~10% of codebase)**

The sync and async test files have massive duplication. This is the highest impact improvement.

**Files affected:**

- `habitify_mcp_server/tests/test_habitify_client.py`
- `habitify_mcp_server/tests/test_habitify_client_async.py`

**Solution:**

- Create `test_base.py` with shared test fixtures and utilities
- Use pytest parameterization for sync/async variants
- Extract common mock response factories

### 2. **Fix Duplicate `with_client` Decorators**

Two identical decorators exist in different modules.

**Files affected:**

- `habitify_mcp_server/tools.py` (lines 29-60)
- `habitify_mcp_server/utils/__init__.py` (lines 169-201)

**Solution:**

- Keep only the one in `utils/__init__.py`
- Update `tools.py` to import from utils

### 3. **Standardize Error Handling**

Currently using broad `except Exception` catches throughout.

**Files affected:**

- `habitify_mcp_server/habitify_client.py` (7 occurrences)
- `habitify_mcp_server/tools.py` (2 occurrences)

**Solution:**

- Create specific exception handlers for httpx exceptions
- Define clear error response patterns
- Use error handler mapping for cleaner code

## Medium Priority Refactoring

### 4. **Simplify Complex Functions**

#### `get_habit_status` in tools.py (118 lines)

**Solution:**

- Split into `_handle_single_date_status()` and `_handle_date_range_status()`
- Extract common validation logic

#### `_handle_error` in habitify_client.py (58 lines)

**Solution:**

- Use error handler mapping pattern
- Reduce nesting levels
- Extract error message formatting

### 5. **Resolve Circular Import Issues**

The codebase has workarounds for circular imports.

**Files affected:**

- `habitify_mcp_server/utils/__init__.py`
- `habitify_mcp_server/utils/habit_resolver.py`

**Solution:**

- Move habit resolution logic to a separate module
- Consider dependency injection pattern
- Restructure module dependencies

### 6. **Create Constants for Magic Values**

**Create new file:** `habitify_mcp_server/constants.py`

```python
from enum import IntEnum

class HTTPStatus(IntEnum):
    UNAUTHORIZED = 401
    NOT_FOUND = 404
    INTERNAL_SERVER_ERROR = 500
    # ... etc

# Status strings should use existing Status enum consistently
```

## Low Priority Improvements

### 7. **Standardize Type Hints**

- Use `str | None` instead of `Optional[str]` (Python 3.10+)
- Add missing return type annotations
- Be consistent with type imports

### 8. **Improve Date Handling**

- Create a centralized date handling utility
- Standardize on fewer date formats
- Reduce conversions between string/datetime/date

### 9. **Extract Common Patterns**

#### Logging Setup (duplicated in examples/)

```python
# Create habitify_mcp_server/logging_config.py
def setup_logging(name: str, level: str = "INFO") -> Logger:
    ...
```

## Implementation Order

1. **Week 1:**

   - Fix duplicate `with_client` decorators (Quick win)
   - Create constants file for magic values
   - Start test refactoring (highest impact)

2. **Week 2:**

   - Complete test refactoring
   - Standardize error handling
   - Fix circular imports

3. **Week 3:**
   - Simplify complex functions
   - Standardize type hints
   - Improve date handling

## Metrics

**Current state:**

- Code duplication: 9.57% tokens
- Test duplication: ~60% between sync/async tests
- Complex functions: 2 functions > 100 lines
- Broad exception catches: 9 occurrences

**Target state:**

- Code duplication: < 5% tokens
- Test duplication: < 10%
- Complex functions: 0 functions > 50 lines
- Broad exception catches: 0 occurrences

## Notes

- All refactoring should maintain backward compatibility
- Add tests for any new utilities created
- Update documentation as needed
- Consider performance implications of changes
