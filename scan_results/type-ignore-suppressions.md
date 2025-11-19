# Type Checker Suppression Scan Report

**Generated**: 2025-11-19
**Total Suppressions Found**: 149 (75 `type: ignore`, 74 `noqa`)
**Files with Suppressions**: 61

---

## Executive Summary

This scan identifies all type checker suppressions (`type: ignore`, `noqa`) across the codebase. The findings are categorized by suppression type and analyzed for fixability.

### Key Metrics

| Category | Count | Assessment |
|----------|-------|------------|
| `type: ignore` | 75 | Mixed - some legitimate, some potentially fixable |
| `noqa` | 74 | Mostly legitimate (AST patterns, side-effects, style) |
| High Priority Patterns | 12 | Attribute access & imports (potentially fixable) |
| Documented Suppressions | 28 | Already have explanatory comments |
| No Documentation | 121 | Need review or documentation |

---

## Suppression Distribution

### By Type

- **`type: ignore[attr-defined]`**: 23 occurrences (most common)
  - Dynamic attribute access on objects with incomplete stubs
  - Status: Mostly legitimate (library limitations or private API access)

- **`type: ignore[unspecified]`** (bare `type: ignore`): 13 occurrences
  - **Status: HIGH PRIORITY** - should be specific or removed
  - Examples: `import docker`, imports in test setup

- **`type: ignore[assignment]`**: 9 occurrences
  - Assigning callable/bound methods to attributes
  - Status: Mostly legitimate (intentional attribute exposure)

- **`type: ignore[override]`**: 9 occurrences
  - Method override variations in MCP patterns and tests
  - Status: Legitimate (intentional type narrowing)

- **`noqa: F401`** (unused import): 31 occurrences
  - Side-effect imports for registration/initialization
  - Status: Legitimate and well-documented use case

- **`noqa: N802`** (invalid name): 13+ occurrences
  - AST visitor pattern (required naming convention)
  - Status: Legitimate - required by AST NodeVisitor API

- **`noqa: B008`**: 7 occurrences
  - Mutable default argument in Typer options
  - Status: Legitimate - Typer design pattern

---

## Detailed Findings

### Category 1: Legitimate Suppressions (Keep with current documentation)

#### AST Visitor Pattern (Legitimate)
Files: `adgn/src/adgn/tools/trivial_patterns.py`, `experimental/flake8-early-bailout/flake8_early_bailout.py`

All `noqa: N802` violations follow the AST visitor pattern where method names MUST match node types:
```python
def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
    # Method name MUST match AST node type per visitor pattern spec
```

**Status**: Keep. These are required by Python's AST API.

#### Side-Effect Imports (Legitimate)
Files: `adgn/props/detectors/__main__.py`, `adgn/props/detectors/cli_custom.py`, `wt/src/wt/server/wt_server.py`

23+ occurrences of `noqa: F401` for imports that exist only for their registration side effects:
```python
from adgn.props.detectors import (
    det_broad_except_order,  # noqa: F401
    det_dynamic_attr_probe,  # noqa: F401
    # ... imported for registration in detector registry
)
```

**Status**: Keep. These are import-for-side-effect and properly documented.

#### Typer Mutable Defaults (Legitimate)
Files: `adgn/src/adgn/llm/llm_edit.py`, `llm/mcp/habitify/habitify_mcp_server/cli.py`

7 occurrences of `noqa: B008` for Typer options:
```python
file_path: Path = typer.Argument(  # noqa: B008
    ..., exists=True, dir_okay=False
)
```

**Status**: Keep. This is Typer's documented design pattern.

#### DBus Method Naming (Legitimate)
Files: `experimental/dbus_fast_example/dbus_service.py`

4 occurrences of `noqa: N802` for DBus method names:
```python
def Ping(self) -> str:  # noqa: N802 - DBus method name
def EmitSignal(self, msg: str) -> None:  # noqa: N802 - DBus method name
```

**Status**: Keep. DBus protocol requires specific naming conventions.

---

### Category 2: Well-Documented Private API Access (Legitimate but needs verification)

These have clear comments explaining WHY they're necessary:

#### pygit2 Incomplete Stubs
**Location**: `wt/src/wt/server/git_manager.py` (3 occurrences)

```python
resolved = repo.resolve_refish(ref)  # type: ignore[attr-defined]
# pygit2 stubs incomplete for resolve_refish
```

**Status**: Legitimate with documentation.
**Action**: Consider adding a TODO to remove after pygit2 stub updates.

#### Import After Environment Setup
**Location**: `gatelet/gatelet/server/conftest.py` (5 occurrences)

```python
from gatelet.server.app import app  # type: ignore[import]
# Imports after env setup (required for config)
```

**Status**: Legitimate with documentation.
**Action**: None - this is a test fixture with justified import order.

#### Monkey Patching (Tests)
**Location**: `homeassistant/iaqi/tests/conftest.py`

```python
def _safe_iterdir(self: pathlib.Path):  # type: ignore[override]
# Monkey-patch for Path.iterdir (test utility)

pathlib.Path.iterdir = _safe_iterdir  # type: ignore[assignment]
# Intentional monkey-patch for testing
```

**Status**: Legitimate for test utilities.

#### MCP Decorator Client Injection
**Location**: `llm/mcp/habitify/habitify_mcp_server/server.py` (4 occurrences)

```python
return await tools.get_habits(  # type: ignore[call-arg]
    # client injected by decorator
```

**Status**: Legitimate - decorator pattern injecting implicit parameter.

---

### Category 3: Type System Edge Cases (Potentially Fixable)

#### Dynamic Attribute Assignment (Intentional Pattern)
**Location**: `wt/src/wt/server/services.py` (3 occurrences)

```python
self.get_client = get_client  # type: ignore[assignment]
# Expose callable as attribute
```

**Analysis**: This is intentional attribute exposure of callables. Could be fixed by:
1. Defining a Protocol for the expected callable type
2. Using TypeVar with bound to declare expected signature
3. Using `@property` decorator instead

**Priority**: Medium. Document the intent or use a proper Protocol.

#### Slice Assignment on deque
**Location**: `dotfiles/local/bin/login_event_webhook_reporter.py`

```python
queue[:0] = batch  # type: ignore[slice-assignment]
# Prepend batch to queue (collections.deque)
```

**Analysis**: `collections.deque` does support slice assignment. This suggests the type hint is wrong (parameter should be `deque[T]` not generic container).

**Priority**: Low - well documented, deque API is correctly typed in modern stdlib.

---

### Category 4: Bare `type: ignore` (HIGH PRIORITY)

13 occurrences of bare `type: ignore` without error code specification. These MUST be made specific:

#### Location 1: Docker Import
**File**: `adgn/src/adgn/agent/server/app.py:13`

```python
import docker  # type: ignore
```

**Issue**: Missing error code. The `docker` package likely has incomplete type hints.

**Fix**: Replace with:
```python
import docker  # type: ignore[import-untyped]
```

#### Location 2: Library Imports
**File**: `experimental/cotrl/llm_rl_experiment.py:13`

```python
import aiofiles  # type: ignore[import-untyped]  # Already specific!
```

**Status**: Already fixed - good pattern to follow.

#### Location 3: Test Fixtures with Mock Returns
**File**: Multiple test files with vague ignores

**Priority**: Convert all bare `type: ignore` to specific codes or fix the underlying type.

---

### Category 5: MCP Private Attribute Access (Requires Investigation)

**File**: `adgn/src/adgn/mcp/stubs/typed_stubs.py` (10 occurrences)

```python
tm = server._tool_manager  # type: ignore[attr-defined]
tools_by_name = tm._tools  # type: ignore[attr-defined]
fm = t.fn_metadata  # type: ignore[attr-defined]
```

**Analysis**: These access private attributes of FastMCP server internals to extract type information for stub generation. This is necessarily fragile due to relying on private APIs.

**Recommendation**:
1. Document clearly why this is necessary (stub extraction from private API)
2. Consider if FastMCP exposes public introspection APIs
3. Pin to known working FastMCP versions

**Status**: Legitimate for specialized use (stub generator), but requires careful maintenance.

---

### Category 6: Test Mocking (Legitimate)

**File**: `adgn/tests/mcp/policy_gateway/test_middleware_lifecycle.py` (9 occurrences)

Examples:
```python
result.error = None  # type: ignore
persistence.save_tool_call = tracking_save  # type: ignore
```

**Analysis**: Tests intentionally mock/replace attributes on test objects to capture behavior.

**Status**: Legitimate for test fixtures. Consider adding `# Test fixture` comment for clarity.

---

### Category 7: Override Pattern (MCP Resource Handlers)

**Files**: Multiple MCP test files with `type: ignore[override]`

```python
async def on_resource_updated(
    self, message: types.ResourceUpdatedNotification
) -> None:  # type: ignore[override]
    # Intentional: subclass narrows handler signature
```

**Analysis**: MCP protocols define base handlers; implementations intentionally narrow return types (None) or parameter types.

**Status**: Legitimate. These are proper override refinements that type checkers flag but are semantically sound.

---

### Category 8: Assignment to Attributes (Intentional)

**File**: `adgn/src/adgn/agent/mcp_bridge/server.py`

```python
compositor_app: FastAPI = running.compositor.http_app()  # type: ignore[assignment]
```

**Analysis**: Intentional type narrowing - we know the return type is more specific than declared.

**Status**: Legitimate. Could use `cast()` for clarity:
```python
compositor_app: FastAPI = cast(FastAPI, running.compositor.http_app())
```

---

## Recommendations by Priority

### High Priority (Review & Fix)

1. **Bare `type: ignore` (13 occurrences)**
   - Make all suppressions specific with error codes
   - Add comments explaining WHY the suppression is needed
   - Examples: `# type: ignore[import-untyped]`, `# type: ignore[attr-defined]`

2. **Investigate MCP Private API Dependencies** (`adgn/src/adgn/mcp/stubs/typed_stubs.py`)
   - Document why private API access is necessary
   - Consider fallback or warning if FastMCP internals change
   - Add version pin comment

### Medium Priority (Document & Validate)

1. **Dynamic Attribute Exposure** (3 occurrences in `wt/src/wt/server/services.py`)
   - Either convert to Protocol-based typing or keep with clear documentation
   - Consider using `@property` if applicable

2. **Enhance Test Fixture Comments**
   - Add `# Test fixture: ...` comments to explain intentional type violations
   - Makes intent clear for future maintainers

### Low Priority (Already Well-Handled)

1. **Legitimate patterns** (AST, side-effects, DBus, Typer)
   - These are already documented and intentional
   - No action needed

---

## Suppression Inventory by File

### Files with Most Suppressions

| File | Count | Type | Assessment |
|------|-------|------|------------|
| `adgn/src/adgn/props/detectors/__main__.py` | 12 | F401 | Legitimate (side-effects) |
| `adgn/src/adgn/props/detectors/cli_custom.py` | 11 | F401 | Legitimate (side-effects) |
| `adgn/src/adgn/tools/trivial_patterns.py` | 11 | N802 | Legitimate (AST pattern) |
| `adgn/src/adgn/mcp/stubs/typed_stubs.py` | 10 | attr-defined | Private API (documented) |
| `adgn/tests/mcp/policy_gateway/test_middleware_lifecycle.py` | 9 | mixed | Test mocks (legitimate) |
| `adgn/src/adgn/mcp/_shared/fastmcp_flat.py` | 7 | attr-defined, misc | Dynamic attribute setting |
| `gatelet/gatelet/server/conftest.py` | 5 | import | Env setup (documented) |
| `experimental/flake8-early-bailout/flake8_early_bailout.py` | 5 | N802, RUF100 | AST pattern + meta-ignore |

---

## Specific Error Code Analysis

### `type: ignore[attr-defined]` (23 occurrences)

**Breakdown**:
- 10: MCP stub generation (`typed_stubs.py`) - private API access
- 3: pygit2 incomplete stubs (documented)
- 3: wt services (attribute exposure - potentially fixable)
- 3: dbus_fast_example (dynamic interface lookup)
- 2: MCP routing assignment (type narrowing)
- 2: Other library limitations

**Assessment**: Mix of legitimate (library stubs), documented (pygit2), and potentially fixable (attribute exposure).

### `type: ignore[unspecified]` (13 occurrences)

**Breakdown**:
- 8: Import statements (docker, aiofiles, ipykernel)
- 3: Test mocking/casting
- 2: Other

**Action Required**: Convert all to specific codes (e.g., `[import-untyped]`, `[index]`).

### `noqa: E402` (3 occurrences)

**Files**:
- `ansible/action_plugins/github_release_*.py` - imports after code (plugin convention)
- `adgn/src/adgn/agent/persist/__init__.py` - import after code

**Assessment**: Documented necessity; consider if reorganization is possible.

---

## Validation Checklist

The following suppressions have been reviewed:

- [x] AST visitor patterns (N802) - Legitimate per Python AST API
- [x] Side-effect imports (F401) - Legitimate, documented
- [x] Typer options (B008) - Legitimate, designed pattern
- [x] DBus method names (N802) - Legitimate per protocol
- [x] Private API access (attr-defined) - Mostly documented, some need comments
- [x] Test mocking - Legitimate for fixtures
- [x] Override patterns - Legitimate type refinement
- [x] Dynamic attributes - Intentional, some need documentation

---

## Action Items

### Immediate (Critical)

1. Convert all 13 bare `type: ignore` to specific error codes
2. Document the MCP stub generator's private API dependency
3. Add comments to test fixture mocks explaining intent

### Near-term (Important)

1. Review attribute exposure in `wt/src/wt/server/services.py` - decide on Protocol or documentation
2. Verify pygit2 version and add version-specific TODO comments
3. Update any bare docstring comments to reference specific error codes

### Future (Nice-to-have)

1. Monitor FastMCP releases for public introspection API alternatives
2. Monitor pygit2 releases for improved type stubs
3. Consider Protocol-based typing for dynamic callables

---

## Summary by Assessment Category

| Category | Count | Recommendation |
|----------|-------|-----------------|
| Legitimate (AST/API requirements) | 28 | Keep as-is |
| Legitimate (side-effects/imports) | 31 | Keep as-is |
| Documented (library limitations) | 10 | Keep with version monitoring |
| Test fixtures | 10+ | Add clarifying comments |
| Bare `type: ignore` | 13 | **Convert to specific codes** |
| Potentially fixable | 5 | Evaluate case-by-case |
| Requires investigation | 3 | Flag for review |

---

## Next Steps

1. **Immediate**: Fix all bare `type: ignore` instances by making them specific
2. **Document**: Add comments to all suppressions without explanation (121 items)
3. **Review**: Assess the 5 potentially fixable items for type system improvements
4. **Monitor**: Watch for library updates (pygit2, FastMCP) that might resolve stubs
