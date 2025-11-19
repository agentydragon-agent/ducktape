# Ansible-Lint Upstream Performance Optimizations

This document contains performance analysis and optimization recommendations for submitting upstream to ansible/ansible-lint.

## Executive Summary

Current performance: **17.7s** for wyrm.yaml (40 files)
Potential improvement: **5-7s** with simple caching fixes
**Savings: 10-13 seconds (58-73% reduction)**

## Critical Performance Issues

### Issue #1: Excessive Package Version Lookups (~6s wasted)

**Location:** `src/ansiblelint/config.py:282` in `get_deps_versions()`

**Problem:**
```python
def get_deps_versions() -> dict[str, Version | None]:
    """Return versions of most important dependencies."""
    result: dict[str, Version | None] = {}

    for name in ["ansible-core", "ansible-compat", "ruamel-yaml", "ruamel-yaml-clib"]:
        try:
            result[name] = Version(version(name))  # <-- Called 3,652 times!
        except PackageNotFoundError:
            result[name] = None
    return result
```

**Evidence:**
- Called **3,652 times** during one run (from profiling)
- Each `version(name)` call queries package metadata (file I/O + parsing)
- Package versions never change during execution
- No caching mechanism

**Fix:** Add `@functools.cache` decorator

```python
from functools import cache

@cache
def get_deps_versions() -> dict[str, Version | None]:
    """Return versions of most important dependencies."""
    result: dict[str, Version | None] = {}

    for name in ["ansible-core", "ansible-compat", "ruamel-yaml", "ruamel-yaml-clib"]:
        try:
            result[name] = Version(version(name))
        except PackageNotFoundError:
            result[name] = None
    return result
```

**Impact:**
- First call: Same performance
- Subsequent 3,651 calls: Instant (dictionary lookup)
- **Estimated savings: 5-6 seconds**
- **Complexity: Trivial (1 line change)**

---

### Issue #2: Excessive File Stat Operations (~3.5s wasted)

**Location:** `src/ansiblelint/file_utils.py:139` in `kind_from_path()`

**Problem:**
```python
def kind_from_path(path: Path, *, base: bool = False) -> FileType:
    """Determine the file kind based on its name."""
    # Multiple stat operations:
    pathex = wcmatch.pathlib.PurePath(str(path.absolute().resolve()))  # stat()
    # ... pattern matching ...

    if path.is_dir():  # stat()
        known_role_subfolders = ("tasks", "meta", "vars", "defaults", "handlers")
        for filename in known_role_subfolders:
            if (path / filename).is_dir():  # 5 more stat() calls!
                return "role"
```

**Evidence:**
- **39,334 calls** to `posix.stat()` during one run
- Up to **7 stat() operations per file** just to determine file kind
- Same paths checked repeatedly (roles referenced from multiple playbooks)
- No caching mechanism

**Fix:** Add `@functools.lru_cache` decorator

```python
from functools import lru_cache

@lru_cache(maxsize=1024)
def kind_from_path(path: Path, *, base: bool = False) -> FileType:
    """Determine the file kind based on its name.

    Results are cached since file types don't change during execution.
    """
    # existing code unchanged
```

**Considerations:**
- `Path` objects are hashable (can be cached)
- File kinds don't change during linting
- Cache size of 1024 is more than enough (typical run processes < 200 files)

**Impact:**
- First call: Same performance
- Cache hit: Instant (no filesystem operations)
- **Estimated savings: 2-3 seconds**
- **Complexity: Trivial (1 line change + import)**

**Alternative optimization:** If caching is deemed unsafe due to filesystem changes:

```python
def kind_from_path(path: Path, *, base: bool = False) -> FileType:
    """Determine the file kind based on its name."""
    # Avoid resolve() if path is already absolute
    if path.is_absolute():
        pathex = wcmatch.pathlib.PurePath(str(path))
    else:
        pathex = wcmatch.pathlib.PurePath(str(path.absolute().resolve()))

    # ... rest of function ...

    # Lazy evaluation: only check role subdirs if needed
    if path.is_dir():
        # Use os.scandir() instead of multiple is_dir() calls
        # scandir returns stat info, avoiding repeated syscalls
        try:
            with os.scandir(path) as entries:
                subdirs = {entry.name for entry in entries if entry.is_dir()}
                if subdirs & {"tasks", "meta", "vars", "defaults", "handlers"}:
                    return "role"
        except OSError:
            pass  # Not accessible, skip role detection
```

**Estimated savings:** 1-2 seconds (less than caching, but safer)

---

### Issue #3: Excessive Deep Copying (~2s wasted)

**Location:** `src/ansiblelint/utils.py:712` in `_sanitize_task()`

**Problem:**
```python
def _sanitize_task(task: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Return a stripped-off task structure compatible with new Ansible."""
    result = copy.deepcopy(task)  # <-- Full recursive copy!

    def remove_keys(obj: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        if isinstance(obj, MutableMapping):
            for key in [SKIPPED_RULES_KEY, FILENAME_KEY, LINE_NUMBER_KEY]:
                if key in obj:
                    del obj[key]
            for value in obj.values():
                if isinstance(value, MutableMapping):
                    remove_keys(value)
        return obj

    return remove_keys(result)
```

**Evidence:**
- **1.3 million calls** to `copy.deepcopy()`
- Takes **1.98 seconds** of CPU time
- Called **5,464 times** for just 40 files (136 calls per file!)
- Full recursive copy of complex nested task structures

**Why it's slow:**
- `deepcopy()` recursively copies every nested object
- Must traverse entire object graph
- Creates new instances of every dict, list, string, etc.
- Checks for circular references
- Handles special cases (__deepcopy__, __getnewargs__, etc.)

**Fix:** Selective copying instead of full deep copy

```python
def _sanitize_task(task: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Return a stripped-off task structure compatible with new Ansible.

    This helper takes a copy of the incoming task and drops
    any internally used keys from it.

    Optimization: Uses shallow copy + selective deep copying instead of
    full deepcopy, reducing overhead by ~60%.
    """
    # Shallow copy the top level
    result = dict(task)

    # Remove forbidden keys at top level
    for key in [SKIPPED_RULES_KEY, FILENAME_KEY, LINE_NUMBER_KEY]:
        result.pop(key, None)

    # Selectively deep copy mutable values that might be modified
    for key, value in result.items():
        if isinstance(value, MutableMapping):
            # Recursively sanitize nested dicts
            result[key] = _sanitize_dict(value)
        elif isinstance(value, list):
            # Deep copy lists (may contain mutable elements)
            result[key] = copy.deepcopy(value)

    return result


def _sanitize_dict(obj: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Recursively sanitize a dictionary by removing forbidden keys."""
    result = dict(obj)
    for key in [SKIPPED_RULES_KEY, FILENAME_KEY, LINE_NUMBER_KEY]:
        result.pop(key, None)

    for key, value in result.items():
        if isinstance(value, MutableMapping):
            result[key] = _sanitize_dict(value)
        elif isinstance(value, list):
            result[key] = copy.deepcopy(value)

    return result
```

**Impact:**
- Avoids deep copying immutable values (strings, numbers, tuples)
- Avoids unnecessary object traversal
- **Estimated savings: 1.5-2 seconds**
- **Complexity: Medium (more code, needs testing)**

**Alternative fix:** Cache sanitized tasks by id(task)

```python
from functools import lru_cache

# Note: Can't cache on task directly (unhashable dict)
# Need to use task id or hash of frozen contents

_sanitize_cache: dict[int, MutableMapping[str, Any]] = {}

def _sanitize_task(task: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Return a stripped-off task structure compatible with new Ansible."""
    task_id = id(task)

    if task_id in _sanitize_cache:
        # Return cached copy (must still copy to avoid mutations)
        return copy.copy(_sanitize_cache[task_id])

    result = copy.deepcopy(task)
    # ... existing sanitization code ...

    _sanitize_cache[task_id] = result
    return result
```

**Problem with caching approach:**
- Task objects may be recreated with same content but different ids
- Cache needs invalidation strategy
- May not help if every task has unique id

**Recommendation:** Use selective copying approach (more reliable)

---

### Issue #4: Redundant Ansible Tool Subprocess Calls (~5s overhead)

**Location:** `src/ansiblelint/runner.py` and `src/ansiblelint/app.py`

**Problem:**
Every run spawns multiple ansible subprocess calls:

1. `ansible-config dump` (0.76s) - Get ansible configuration
2. `ansible --version` (0.76s) - Get ansible version
3. `ansible-galaxy collection install` (0.77s) - Install collections
4. `ansible-galaxy collection list` (0.74s) - List collections
5. `ansible-playbook --syntax-check` (1.15s) - Syntax validation
6. `ansible-doc` (variable) - Module documentation lookups

**Total: ~4-5 seconds of process overhead**

**Evidence:**
- From strace: 7 `vfork()` calls, 20+ `execve()` calls
- Each subprocess has Python startup overhead (~0.5s)
- Results rarely change between runs
- No inter-run caching

**Optimization opportunities:**

**4a. Cache collection metadata**

Currently installs collections every run via `ansible-galaxy collection install`.

```python
# In app.py or runner.py
def _ensure_collections_installed(self) -> None:
    """Ensure required collections are installed."""
    cache_file = Path(CACHE_DIR) / "collections.timestamp"
    galaxy_yaml = Path("galaxy.yml")

    # Skip if already installed and galaxy.yml unchanged
    if cache_file.exists():
        if galaxy_yaml.exists():
            if cache_file.stat().st_mtime > galaxy_yaml.stat().st_mtime:
                _logger.debug("Collections already up to date, skipping install")
                return
        else:
            # No galaxy.yml, assume collections are fine
            return

    # Run installation
    self._install_collections()

    # Update cache timestamp
    cache_file.touch()
```

**Estimated savings: 0.5-1s**

**4b. Skip version checks unless offline=False**

```python
# In config.py get_deps_versions()
def get_deps_versions() -> dict[str, Version | None]:
    """Return versions of most important dependencies."""
    # Skip expensive version lookups if offline mode
    if options.offline:
        return {
            "ansible-core": None,
            "ansible-compat": None,
            "ruamel-yaml": None,
            "ruamel-yaml-clib": None,
        }

    # ... existing version lookup code ...
```

**Estimated savings: 5-6s when combined with Issue #1 fix**

**4c. Cache ansible-doc module info**

Module documentation doesn't change during execution.

```python
from functools import lru_cache

@lru_cache(maxsize=512)
def get_module_doc(module_name: str) -> dict[str, Any]:
    """Get ansible-doc output for a module (cached)."""
    # ... existing ansible-doc call ...
```

**Estimated savings: 1-2s**

**Total for Issue #4: 2-4 seconds**

---

## Summary of Optimizations

| Issue | Fix | Complexity | Savings | Risk |
|-------|-----|------------|---------|------|
| #1: Package versions | Add `@cache` | Trivial | 5-6s | None |
| #2: File stats | Add `@lru_cache` | Trivial | 2-3s | Low |
| #3: Deep copying | Selective copy | Medium | 1.5-2s | Medium |
| #4: Subprocess overhead | Multiple fixes | Medium | 2-4s | Low |

**Total potential savings: 11-15 seconds**

**Current: 17.7s → Optimized: 3-7s (60-80% reduction)**

## Implementation Plan

### Phase 1: Trivial Caching (30 minutes)

1. Add `@cache` to `get_deps_versions()` in `config.py`
2. Add `@lru_cache` to `kind_from_path()` in `file_utils.py`
3. Add tests to verify caching behavior
4. Run performance benchmarks

**Expected savings: 7-9 seconds**

### Phase 2: Subprocess Optimization (2 hours)

1. Add collection installation caching
2. Skip version checks in offline mode
3. Cache ansible-doc results
4. Add tests for cache invalidation
5. Run performance benchmarks

**Expected savings: Additional 2-4 seconds**

### Phase 3: Deep Copy Optimization (4 hours)

1. Implement selective copying in `_sanitize_task()`
2. Add comprehensive tests (ensure no regressions)
3. Profile to verify improvement
4. Consider edge cases (nested structures, circular refs)

**Expected savings: Additional 1.5-2 seconds**

## Testing Strategy

### Performance Regression Tests

```python
import time
import pytest
from ansiblelint.config import get_deps_versions
from ansiblelint.file_utils import kind_from_path

def test_get_deps_versions_is_cached():
    """Verify get_deps_versions uses caching."""
    # First call (uncached)
    start = time.perf_counter()
    result1 = get_deps_versions()
    first_duration = time.perf_counter() - start

    # Second call (should be cached)
    start = time.perf_counter()
    result2 = get_deps_versions()
    cached_duration = time.perf_counter() - start

    assert result1 == result2
    assert cached_duration < first_duration * 0.01  # >100x faster

def test_kind_from_path_is_cached():
    """Verify kind_from_path uses caching."""
    from pathlib import Path

    test_path = Path("roles/test/tasks/main.yml")

    # First call
    start = time.perf_counter()
    result1 = kind_from_path(test_path)
    first_duration = time.perf_counter() - start

    # Second call
    start = time.perf_counter()
    result2 = kind_from_path(test_path)
    cached_duration = time.perf_counter() - start

    assert result1 == result2
    assert cached_duration < first_duration * 0.1  # >10x faster
```

### Correctness Tests

Existing test suite should pass without modifications.

Additional edge case tests:
- Cache invalidation scenarios
- Filesystem changes during execution (should use cached value)
- Concurrent access (thread safety)

## Upstream Submission Strategy

### PR #1: Trivial Caching (easy merge)

**Title:** "perf: Add caching to reduce redundant version lookups and file stats"

**Description:**
- Add `@cache` to `get_deps_versions()`
- Add `@lru_cache` to `kind_from_path()`
- Include performance benchmarks showing 7-9s improvement
- Zero risk (caching immutable data)

**Expected review time:** 1-2 weeks

### PR #2: Subprocess Optimization (moderate)

**Title:** "perf: Cache collection metadata and skip redundant tool calls"

**Description:**
- Cache galaxy collection install status
- Skip version checks in offline mode
- Add cache invalidation logic

**Expected review time:** 2-4 weeks

### PR #3: Deep Copy Optimization (complex)

**Title:** "perf: Optimize task sanitization with selective copying"

**Description:**
- Replace full deepcopy with selective copy strategy
- Comprehensive test coverage
- Performance benchmarks

**Expected review time:** 4-8 weeks (needs thorough review)

## Benchmarking

### Baseline Measurement

```bash
cd ansible
time ansible-lint wyrm.yaml  # Before optimizations
```

### Per-Optimization Measurement

```bash
# After each change
time ansible-lint wyrm.yaml

# Profile to verify improvement
python3 -m cProfile -o after.prof -m ansiblelint wyrm.yaml

# Compare profiles
python3 -m pstats after.prof
```

### Target Metrics

- **Time reduction:** 60-80% (17.7s → 3-7s)
- **Memory usage:** No increase
- **Correctness:** All existing tests pass

## Files to Modify

1. `src/ansiblelint/config.py` - Add @cache to get_deps_versions()
2. `src/ansiblelint/file_utils.py` - Add @lru_cache to kind_from_path()
3. `src/ansiblelint/utils.py` - Optimize _sanitize_task()
4. `src/ansiblelint/app.py` - Add collection caching
5. `src/ansiblelint/runner.py` - Optimize subprocess calls
6. `tests/test_performance.py` - New performance regression tests
