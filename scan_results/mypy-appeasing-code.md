# Scan Results: Mypy-Appeasing Code Antipatterns

**Scan Date:** 2025-11-19
**Scope:** Full Python codebase (ducktape)
**Total Cast Instances Found:** 80+
**Total TypeAdapter Instances Found:** 50+

---

## Executive Summary

This scan identified mypy-appeasing code patterns across the codebase. The primary findings are:

1. **Critical Issue: Unnecessary casts after `.model_validate()`** (HIGH PRIORITY)
   - Multiple instances where `.model_validate()` already returns the correct type
   - These casts add zero semantic value and suggest misunderstanding of Pydantic's type inference

2. **Secondary Pattern: Valid casts after `isinstance` checks** (LOWER PRIORITY)
   - Defensive casts following runtime type checks
   - Generally acceptable but could be reviewed for necessity

3. **Database Access Pattern: SQLite row casts** (ACCEPTABLE)
   - Casts from database rows (typed as `Any`) to concrete types
   - Necessary due to SQLite driver limitations
   - Could be centralized with a helper function

4. **TypeAdapter Usage: Mixed Quality**
   - Many legitimate uses as function parameters
   - Some well-placed module-level constants
   - Generally good pattern but some redundant intermediate variables found

---

## Critical Findings

### Pattern 1: Unnecessary Casts After `.model_validate()`

These are the most problematic — Pydantic's `.model_validate()` already returns the correct type:

#### Location 1: `/home/user/ducktape/wt/src/wt/shared/protocol.py:479`
```python
def parse_request(data: str) -> Request:
    try:
        raw_data = json.loads(data)
        return cast(Request, Request.model_validate(raw_data))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON (parse error): {e}") from e
```

**Issue:** `Request.model_validate(raw_data)` already has return type `Request`. The cast is redundant.

**Fix:**
```python
def parse_request(data: str) -> Request:
    try:
        raw_data = json.loads(data)
        return Request.model_validate(raw_data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON (parse error): {e}") from e
```

**Reasoning:** Remove the cast entirely. Mypy sees `Request.model_validate()` returns `Request`.

---

#### Location 2: `/home/user/ducktape/tana/src/tana/graph/workspace.py:58`
```python
return cast(BaseNode, node_model.model_validate(raw))
```

**Issue:** `node_model.model_validate(raw)` already returns the bound type (BaseNode subclass).

**Fix:** Remove the cast:
```python
return node_model.model_validate(raw)
```

---

#### Location 3: `/home/user/ducktape/tana/src/tana/export/export_node_subset.py:177`
```python
return cast(BaseNode, node_model.model_validate(raw))
```

**Same issue as Location 2.**

---

#### Location 4: `/home/user/ducktape/adgn/src/adgn/agent/presets.py:38`
```python
return cast(dict[str, JsonValue], data)
```

**Issue:** Need to verify what `data` is. If it's already `dict[str, JsonValue]`, cast is unnecessary.

**Research Required:** Check the function signature and return type of the assignment.

---

### Pattern 2: Unnecessary Typed Variable Assignment → Immediate Return

Found several instances where a variable is typed solely to annotate the return:

#### Location: `/home/user/ducktape/adgn/src/adgn/props/lint_issue.py:98`
```python
body: ConsoleRenderable = bits[0] if len(bits) == 1 else cast(ConsoleRenderable, Group(*tuple(bits)))
return body
```

**Better Pattern:**
```python
return bits[0] if len(bits) == 1 else Group(*tuple(bits))
```

**If Group isn't properly typed as ConsoleRenderable**, that's the real issue to fix upstream.

---

## Secondary Findings: Legitimate Casts (After isinstance Checks)

These casts follow runtime type narrowing and are generally acceptable:

### Location: `/home/user/ducktape/adgn/src/adgn/inop/prompting/truncation_utils.py:49, 63, 66`
```python
if files and isinstance(files[0], FileInfo):
    for fi in cast(list[FileInfo], files):
        out.append((fi.path, fi.content, fi))
else:
    for d in cast(list[dict[str, str]], files):
        out.append((d["path"], d["content"], d))
```

**Assessment:** ACCEPTABLE
**Reason:** The isinstance check justifies the cast. However, this pattern could be improved:

**Alternative (better typing):**
```python
def _normalize_files(
    self, files: list[FileInfo] | list[dict[str, str]]
) -> list[tuple[str, str, dict[str, str] | FileInfo]]:
    if files and isinstance(files[0], FileInfo):
        return [(fi.path, fi.content, fi) for fi in files]  # No cast needed!
    else:
        return [(d["path"], d["content"], d) for d in files]
```

With explicit union type on the parameter, the isinstance check narrows correctly and casts become unnecessary.

---

### Location: `/home/user/ducktape/wt/src/wt/client/wt_client.py:279`
```python
ids: list[WorktreeID] = cast(list[WorktreeID], worktree_ids) if worktree_ids is not None else []
```

**Assessment:** ACCEPTABLE
**Reason:** Defensive cast after None check. The function parameter is likely `list[WorktreeID] | None`.

**Better Pattern:** Update parameter annotation:
```python
def some_method(worktree_ids: list[WorktreeID] | None) -> ...:
    ids = worktree_ids or []
    # Now mypy knows ids is list[WorktreeID] without a cast
```

---

## Tertiary Findings: SQLite Database Row Casts

These are **NECESSARY** due to SQLite driver typing limitations:

### Locations: `/home/user/ducktape/adgn/src/adgn/agent/persist/sqlite.py`

Lines: 225, 242, 311, 355, 357, 382, 383, 384, 402, 703, 704, 766, 767

**Example:**
```python
async for r in cur:
    meta_val = AgentMetadata.model_validate_json(cast(str, r["metadata"]))
```

**Assessment:** NECESSARY
**Reason:** SQLite returns `Any` for dictionary keys. The cast to `str` is justified.

**Recommendation:** Create a centralized helper function to reduce duplication:

```python
def _get_str(row: Any, key: str) -> str:
    """Extract string from SQLite row, with cast."""
    return cast(str, row[key])

def _get_datetime(row: Any, key: str) -> datetime:
    """Extract datetime from SQLite row."""
    return datetime.fromisoformat(cast(str, row[key]))
```

Then usage becomes cleaner:
```python
meta_val = AgentMetadata.model_validate_json(_get_str(r, "metadata"))
created_at = _get_datetime(r, "created_at")
```

---

## TypeAdapter Usage Analysis

### Good Patterns (Module-Level Constants)

**Location: `/home/user/ducktape/ember/src/ember/config.py:44`**
```python
_SLEEP_POLICY_ADAPTER = TypeAdapter(SleepUntilUserMessagePolicy)
```

**Assessment:** GOOD
**Reason:** Reused adapter stored as a module constant. Avoids recreating it on each call.

**Similar Good Patterns:**
- `/home/user/ducktape/adgn/src/adgn/rspcache/models.py:20-22` (RESPONSE_ADAPTER, ERROR_ADAPTER, USAGE_ADAPTER)
- `/home/user/ducktape/adgn/src/adgn/mcp/_shared/urls.py:6` (ANY_URL adapter)

### Acceptable Patterns (Function Parameters)

**Locations:** wt/src/wt/client/wt_client.py:467, 281, 448, 453, etc.

```python
async def _rpc(self, method: str, params_model: BaseModel | dict[str, object], result_adapter: TypeAdapter[T]) -> T:
    ...
    return await self._rpc("get_status", params, TypeAdapter(StatusResponse))
```

**Assessment:** ACCEPTABLE
**Reason:** TypeAdapter is created and immediately used as a function argument. This is the standard pattern.

---

## Summary of Issues by Category

| Category | Count | Severity | Action |
|----------|-------|----------|--------|
| Casts after `.model_validate()` | 3 | HIGH | Remove immediately |
| Typed variable → immediate return | 1 | MEDIUM | Simplify |
| Casts after `isinstance` checks | 5+ | LOW | Consider type union improvement |
| SQLite database row casts | 13+ | LOW | Centralize in helpers |
| TypeAdapter module constants | 8+ | NONE | Keep as-is |
| TypeAdapter function parameters | 40+ | NONE | Keep as-is |
| Other defensive casts | 20+ | LOW | Review case-by-case |

---

## Recommended Actions (Priority Order)

### Priority 1: Remove Unnecessary Casts (HIGH)

1. **File:** `/home/user/ducktape/wt/src/wt/shared/protocol.py:479`
   - Remove: `cast(Request, ...)`
   - Replace with just: `Request.model_validate(raw_data)`

2. **File:** `/home/user/ducktape/tana/src/tana/graph/workspace.py:58`
   - Remove: `cast(BaseNode, ...)`
   - Replace with: `node_model.model_validate(raw)`

3. **File:** `/home/user/ducktape/tana/src/tana/export/export_node_subset.py:177`
   - Same as above

4. **File:** `/home/user/ducktape/adgn/src/adgn/agent/presets.py:38`
   - Verify the type and remove if unnecessary

---

### Priority 2: Improve Type Annotations (MEDIUM)

1. **File:** `/home/user/ducktape/adgn/src/adgn/inop/prompting/truncation_utils.py`
   - Update parameter type: `files: list[FileInfo] | list[dict[str, str]]`
   - Remove casts in isinstance branches

2. **File:** `/home/user/ducktape/wt/src/wt/client/wt_client.py:279`
   - Update pattern to handle `None` without cast

---

### Priority 3: Centralize SQLite Helpers (LOW)

Create helper functions in `/home/user/ducktape/adgn/src/adgn/agent/persist/sqlite.py`:

```python
def _get_str(row: Any, key: str) -> str:
    return cast(str, row[key])

def _get_datetime(row: Any, key: str) -> datetime:
    return datetime.fromisoformat(cast(str, row[key]))

def _get_optional_datetime(row: Any, key: str) -> datetime | None:
    val = row[key]
    return datetime.fromisoformat(cast(str, val)) if val else None
```

---

## Verification Strategy

After making fixes, run:

```bash
# Test that mypy still passes
mypy --strict adgn/src/adgn/agent/persist/sqlite.py

# Test module-by-module for removed casts
rg --type py "cast\(" --no-heading | wc -l

# Run test suite
pytest adgn/tests/
```

---

## False Positives / Exceptions

The following cast patterns were reviewed and deemed ACCEPTABLE:

1. **Function wrapper casts** (`llm/mcp/habitify/habitify_mcp_server/utils/__init__.py:139,171`)
   - These are decorators returning generic functions; casts are justified for type safety

2. **Async return type narrowing** (e.g., `adgn/src/adgn/openai_utils/retry.py:56`)
   - Wrapping async functions in decorators sometimes requires casts

3. **Third-party library typing gaps**
   - Multiple casts in `adgn/src/adgn/mcp/_shared/fastmcp_flat.py` for FastMCP objects
   - These may be necessary until FastMCP improves its type stubs

4. **Test code**
   - Casts in `ember/tests/` and `adgn/tests/` are acceptable for testing purposes

---

## Notes for Future Maintenance

1. **Gradual Migration:** Fix Priority 1 items immediately. Priorities 2-3 can be batched into a future refactoring.

2. **Library Updates:** If library versions change:
   - Check for improved type stubs (e.g., `types-sqlalchemy`)
   - Re-run this scan to identify newly-unnecessary casts

3. **Code Review:** Add this to code review checklist:
   - Casts after `.model_validate()` → flag and remove
   - Typed variables that immediately return → simplify
   - Database row access → suggest using centralized helpers

4. **Documentation:** Add guidelines to project documentation about when casts are acceptable vs. when they indicate a real type problem.

---

## Appendix: Full Cast Locations Reference

### High-Priority Removals
- `/home/user/ducktape/wt/src/wt/shared/protocol.py:479`
- `/home/user/ducktape/tana/src/tana/graph/workspace.py:58`
- `/home/user/ducktape/tana/src/tana/export/export_node_subset.py:177`

### Medium-Priority Reviews
- `/home/user/ducktape/adgn/src/adgn/agent/presets.py:38`
- `/home/user/ducktape/adgn/src/adgn/inop/prompting/truncation_utils.py:49,63,66`
- `/home/user/ducktape/adgn/src/adgn/props/lint_issue.py:98`
- `/home/user/ducktape/wt/src/wt/client/wt_client.py:279`

### SQLite Database Casts (Consolidate)
- `/home/user/ducktape/adgn/src/adgn/agent/persist/sqlite.py:225,242,311,355,357,382,383,384,402,703,704,766,767`

### Acceptable Patterns (No Action)
- All TypeAdapter module-level constants
- All TypeAdapter function parameters
- All casts in test files
- All casts in decorator/wrapper functions

---

**Report Generated:** 2025-11-19
**Scan Tool:** Grep pattern matching + manual analysis
**Next Review:** After implementing Priority 1-2 fixes
