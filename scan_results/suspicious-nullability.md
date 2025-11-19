# Suspicious Nullability Scan Report

**Scan Date**: 2025-11-19
**Scan Type**: Code Quality - Nullability Patterns
**Codebase**: /home/user/ducktape
**Python Files Analyzed**: 1000+

## Executive Summary

This scan identifies suspicious nullability patterns in the codebase that suggest potential type system misuse or architectural issues. The scan found **194 distinct suspicious patterns** across the repository:

- **Assert `is not None` statements**: 30 files (27 test, 3 production)
- **Functions with nullable parameters**: 163 files
- **Return None propagation patterns**: 2 files
- **Severity distribution**:
  - HIGH: 3 production files with assertions
  - MEDIUM: Multiple multi-parameter nullable functions
  - LOW: Widespread nullable parameters in utility/test code

## Key Findings

### 1. HIGH SEVERITY: Production Code Using `assert` for Type Narrowing

Three production files use `assert x is not None` to narrow types, which indicates suspicious typing:

#### File: `/adgn/src/adgn/agent/mcp_bridge/cli.py` (Line ~170)
```python
else:
    # Multi-agent mode: create both MCP server and management UI
    assert auth_tokens_path is not None  # ← HIGH SEVERITY

    # Create shared infrastructure registry
```

**Issue**: `auth_tokens_path` parameter is typed as `str | None` but the code immediately asserts it's not None. This suggests:
- Parameter should be required (not nullable) in this code path
- The function logic should be refactored to handle the optional case at the boundary

**Fix Strategy**: Refactor to handle None at function entry:
```python
# BEFORE
def cli_main(agent_id: str | None, auth_tokens_path: str | None):
    if agent_id:
        # single-agent mode
    else:
        assert auth_tokens_path is not None  # ← Anti-pattern

# AFTER - Handle None at boundary
def cli_main(agent_id: str | None, auth_tokens_path: str | None):
    if agent_id:
        # single-agent mode
        single_agent(agent_id)
    elif auth_tokens_path:
        # multi-agent mode
        multi_agent(auth_tokens_path)
    else:
        raise ValueError("Either agent_id or auth_tokens_path required")
```

#### File: `/adgn/src/adgn/agent/runtime/builder.py` (Line ~85)
```python
if with_ui:
    assert ui_bus is not None  # ← HIGH SEVERITY
    await running.attach_sidecar(UISidecar(ui_bus))
```

**Issue**: `ui_bus` is checked after a conditional. The assertion suggests:
- `ui_bus` should not be optional, or
- The relationship between `with_ui` and `ui_bus` should be encoded in the type system

**Fix Strategy**:
```python
# BEFORE
def start_builder(with_ui: bool, ui_bus: UIBus | None):
    if with_ui:
        assert ui_bus is not None  # Anti-pattern

# AFTER - Encode the relationship in types
def start_builder(ui_config: UIConfig | None):
    if ui_config:
        await running.attach_sidecar(UISidecar(ui_config.bus))
    # ui_bus non-nullable when with_ui=true
```

#### File: `/adgn/src/adgn/props/cli_app/main.py` (Lines ~666, ~693)
```python
# Line 666
assert submit_state.result is not None, "Critic did not call submit_result or submit_error?"

# Line 693
assert path is not None  # After "if specimen is not None" check
return build_scope_text(["/workspace/**"]), path.name
```

**Issue**: Two assertions in CLI main function:
1. `submit_state.result` - result of critic evaluation should always return result or error (not both None)
2. `path` - asserted only after checking `specimen is None`

**Fix Strategy**:
```python
# BEFORE (line 666)
if submit_state.error is not None:
    return 2
assert submit_state.result is not None  # If error is None, result must be not None

# AFTER - Use type narrowing or discriminated union
# Either change SubmitState to guarantee one or the other:
class SubmitState(BaseModel):
    result: Result | None = None
    error: str | None = None

    @field_validator('result', 'error')
    def one_must_be_set(self):
        if (self.result is None and self.error is None):
            raise ValueError("One of result or error must be set")

# Then code becomes:
if submit_state.error is not None:
    return 2
# Type system guarantees result is not None if error is None
handle_result(submit_state.result)
```

### 2. MEDIUM SEVERITY: Multiple Nullable Parameters in Single Function

**30+ functions** accept multiple nullable parameters that are often all required:

#### Pattern Example 1: `/llm/mcp/habitify/habitify_mcp_server/server.py`
```python
async def get_habit(id: str | None = None, name: str | None = None) -> dict[str, Any]:
    return await tools.get_habit(id=id, name=name)
```

**Issues**:
- Both parameters optional, but typically one is required
- Caller must provide exactly one (implicit contract)
- Type system doesn't enforce this

**Fix Strategy**:
```python
# BEFORE
async def get_habit(id: str | None = None, name: str | None = None):
    ...

# AFTER - Use discriminated union to make intent explicit
from typing import Annotated, Literal
from pydantic import BaseModel, Field

class GetHabitByID(BaseModel):
    query_type: Literal["id"]
    id: str

class GetHabitByName(BaseModel):
    query_type: Literal["name"]
    name: str

GetHabitQuery = Annotated[GetHabitByID | GetHabitByName, Field(discriminator="query_type")]

async def get_habit(query: GetHabitQuery) -> dict[str, Any]:
    ...
```

#### Pattern Example 2: `/wt/src/wt/client/handlers.py`
```python
async def handle_path_command(config, worktree_name: str | None = None, subpath: str | None = None) -> None:
    if worktree_name is None and subpath is None:
        # Case 1: both None
        p = await client.resolve_path_simple(None, "/")
    elif subpath is None:
        # Case 2: only subpath is None
        arg = worktree_name or ""
    # ... more cases
```

**Issue**: Function handles 4 different states of 2 optional parameters (None/NotNone combinations)

**Fix Strategy**: Use overloads or explicit union types:
```python
from typing import overload

@overload
async def handle_path_command(config, *, worktree_name: str, subpath: None = None) -> None: ...

@overload
async def handle_path_command(config, *, worktree_name: None = None, subpath: str) -> None: ...

@overload
async def handle_path_command(config, *, worktree_name: str, subpath: str) -> None: ...

async def handle_path_command(config, worktree_name: str | None = None, subpath: str | None = None) -> None:
    ...
```

### 3. MEDIUM SEVERITY: None Propagation Through Multiple Layers

**2 files** propagate None through multiple function layers:

#### `/wt/src/wt/server/services.py`
```python
def get_current_branch(repo) -> str | None:
    if repo.head_is_detached:
        return None
    shorthand = repo.head.shorthand
    return shorthand if shorthand else None  # ← Double None check
```

**Issue**: None is propagated when it might be better to use an empty string or raise

#### `/wt/src/wt/server/gitstatusd_listener.py`
```python
def _safe_get_optional_string(fields: list[str], index: int) -> str | None:
    """Get optional string field, returning None for empty strings."""
    value = fields[index]
    return value if value else None
```

**Issue**: Function converts empty strings to None, which spreads None handling upstream

**Fix Strategy**: Handle None once at the boundary:
```python
# BEFORE
def get_branch_info() -> BranchInfo | None:
    if not repo.branch:
        return None
    return BranchInfo(name=repo.branch)

# AFTER - Handle None at call site
def get_branch_info(repo) -> BranchInfo:
    if not repo.branch:
        raise ValueError("Repository has no branch (detached HEAD)")
    return BranchInfo(name=repo.branch)

# Caller:
try:
    branch = get_branch_info(repo)
except ValueError:
    # Handle detached HEAD case
    pass
```

### 4. LOW SEVERITY: Widespread Nullable Parameters in Test Code

**27 test files** use assertions on nullable values. This is expected in tests but indicates:
- Test fixtures return nullable types when they should return concrete types
- Test setup could be improved to guarantee non-nullable values

**Examples**:
- `adgn/tests/agent/mcp_bridge/test_agents_server.py`: Multiple assertions on query results
- `adgn/tests/agent/persist/test_integration.py`: Assertions on persistence queries
- `llm/ducktape_llm_common/tests/claude_linter_v2/test_*.py`: Config lookups returning None

**Fix Strategy**: Improve test fixtures:
```python
# BEFORE
def test_something():
    preset = next((p for p in presets if p["name"] == "default"), None)
    assert preset is not None  # ← Defensive

# AFTER - Fixture guarantees non-None
@pytest.fixture
def default_preset(presets):
    """Return default preset (guaranteed non-None)."""
    result = next((p for p in presets if p["name"] == "default"), None)
    assert result is not None, "Fixture setup error: default preset missing"
    return result

def test_something(default_preset):
    # default_preset is guaranteed non-None, no assertion needed
    assert default_preset["enabled"] is True
```

## Detailed Analysis by Category

### A. Functions with Nullable Parameters (163 files)

These files define functions with one or more `T | None` parameters:

**Non-test files (High Priority)**:
- `adgn/src/adgn/agent/mcp_bridge/cli.py` - Multiple nullable CLI parameters
- `adgn/src/adgn/inop/runners/base.py` - Subprocess creation with nullable config
- `adgn/src/adgn/props/cli_app/main.py` - CLI handling with optional paths
- `experimental/ember_evals/definitions.py` - Evaluation API with optional container
- `experimental/ember_evals/executor.py` - Runtime exec with optional container
- `experimental/webhook_inbox/webhook_inbox.py` - Webhook validation with optional key
- `gatelet/gatelet/server/auth/webhook_auth.py` - Auth validation with optional credentials
- `gatelet/gatelet/server/auth/dependencies.py` - Auth context initialization
- `llm/mcp/habitify/habitify_mcp_server/*.py` - Habit API with multiple optional lookup fields
- `wt/src/wt/client/handlers.py` - Worktree path resolution with multiple optional parameters
- `wt/src/wt/client/view_formatter.py` - Formatting with optional config and PR info
- `wt/src/wt/server/rpc.py` - RPC response with optional data

**Test files** (27 files): Mostly query assertions and fixture None-checks

### B. Assertions on Nullable Values (30 files)

All 30 files use `assert x is not None` pattern:
- **Production (3)**: Flagged as HIGH severity above
- **Tests (27)**: Indicative of poor fixture design

### C. None Propagation (2 files)

Functions that return `X | None` and propagate None from nullable inputs:
- `/wt/src/wt/server/services.py` - Git operations returning None
- `/wt/src/wt/server/gitstatusd_listener.py` - Git status field parsing

## Root Cause Analysis

### Why Suspicious Nullability Exists

1. **External API Constraints**
   - Docker API returns nullable fields (`container.id | None`)
   - Git operations can return None (no branch, detached HEAD)
   - Database queries return None for "not found"
   - **Solution**: Type narrowing helpers at boundaries

2. **Optional Configuration**
   - CLI arguments are often optional
   - Feature flags make parameters optional
   - **Solution**: Handle at entry boundary, don't pass None downstream

3. **Defensive Programming**
   - Functions written to handle `None` "just in case"
   - No validation of requirements at call sites
   - **Solution**: Fix call sites to provide required values

4. **Poor Fixture Design**
   - Test setup returns nullable values
   - Tests assert values aren't None
   - **Solution**: Improve fixtures to guarantee non-nullable returns

5. **Multi-Parameter Optional Functions**
   - "At least one" or "exactly one" constraints not encoded in types
   - Use `| None` for all parameters, add runtime validation
   - **Solution**: Use union types or function overloads

## Recommendations

### Priority 1: Fix Production Assertions (HIGH)

**Action**: Eliminate assertions in production code by refactoring to handle None at boundaries.

**Files to Fix**:
1. `/adgn/src/adgn/agent/mcp_bridge/cli.py` - Refactor multi-agent mode check
2. `/adgn/src/adgn/agent/runtime/builder.py` - Encode UI requirement in types
3. `/adgn/src/adgn/props/cli_app/main.py` - Fix submit_state contract and path handling

**Effort**: ~4-6 hours
**Impact**: Remove false sense of confidence from assertions, improve type safety

### Priority 2: Fix Multi-Parameter Nullable Functions (MEDIUM)

**Action**: For functions with 2+ nullable parameters, refactor to use explicit union types or function overloads.

**Key Files to Refactor**:
- `/llm/mcp/habitify/habitify_mcp_server/*.py` - Habitat API (id vs name lookup)
- `/wt/src/wt/client/handlers.py` - Worktree path resolution
- `/adgn/src/adgn/inop/engine/exceptions.py` - Exception with multiple nullable fields

**Effort**: ~8-12 hours
**Impact**: Prevent runtime errors where None combinations are invalid

### Priority 3: Eliminate None Propagation (MEDIUM)

**Action**: Handle None once at source; pass non-None values downstream.

**Files to Fix**:
- `/wt/src/wt/server/services.py` - Git branch queries
- `/wt/src/wt/server/gitstatusd_listener.py` - Git status parsing

**Approach**:
1. Identify where None originates (external API, database, etc.)
2. Handle None at that boundary
3. Pass non-None type downstream

**Effort**: ~3-4 hours
**Impact**: Simplify downstream code, reduce None checks

### Priority 4: Improve Test Fixtures (LOW)

**Action**: Create fixtures that guarantee non-nullable returns.

**Approach**:
- Add assertions in fixture setup (not in tests)
- Mark fixtures with `@pytest.fixture` contract in docstring
- Use `pytest.fail()` instead of raising to be explicit

**Effort**: ~2-3 hours per test file
**Impact**: Cleaner test code, better error messages

## Implementation Guidelines

Follow the fix philosophy from the scan document:

1. **Question the type declaration**: Why is it nullable?
   - External API constraint?
   - Optional feature?
   - "Not found" vs "error" distinction?

2. **Propagate non-nullability upward**: Change the type signature
   - Remove `| None` from downstream functions
   - Handle None at source, not in business logic

3. **Create type-narrowing helpers**: When needed
   ```python
   def _require_container_id(container: Container) -> str:
       if container.id is None:
           raise RuntimeError("Container has no ID (should never happen)")
       return container.id
   ```

4. **Use proper types**: Not bare assertions
   - Discriminated unions for "one of N"
   - Function overloads for optional parameters
   - TypeGuard for type narrowing

## Validation Commands

After fixing, run these to verify:

```bash
# Type checking
mypy --strict adgn/src/adgn/agent/

# Linting
ruff check adgn/src/adgn/agent/ --fix

# Re-run this scan
python3 prompts/scans/run_suspicious_nullability.py

# Run tests
pytest adgn/tests/ -v
```

## Related Documentation

- **Scan Definition**: `prompts/scans/suspicious-nullability.md`
- **Shared Context**: `prompts/shared-context.md`
- **AGENTS.md**: Conventions and DoD items

## Appendix: Pattern Definitions

### Assert is Not None
```
Pattern: assert <var> is not None
Reason: Variable types suggest it can be None, but code asserts it isn't
Severity: MEDIUM to HIGH (higher in production code)
```

### Nullable Parameters That Immediately Raise
```
Pattern: def f(x: T | None): if x is None: raise ...
Reason: Parameter accepts None but function cannot handle it
Severity: HIGH
```

### Multiple Nullable Parameters
```
Pattern: def f(a: T1 | None, b: T2 | None, ...)
Reason: Some parameter combinations may be invalid but type system allows all
Severity: MEDIUM
```

### None Propagation Through Layers
```
Pattern: Multiple functions returning X | None when they chain together
Reason: None handling scattered across call stack instead of at source
Severity: MEDIUM
```

### Semantically Impossible None
```
Pattern: Field typed as T | None but initialized in __init__ and never reassigned
Reason: Type claim doesn't match semantic guarantee
Severity: MEDIUM
```

---

**Report Generated**: 2025-11-19
**Next Scan Recommended**: After fixes to Priority 1 items
**Maintenance**: Re-run before major releases to catch regressions
