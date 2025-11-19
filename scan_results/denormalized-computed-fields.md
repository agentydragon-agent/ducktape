# Code Quality Scan Report: Denormalized and Computed Fields

**Scan Date**: 2025-11-19
**Scan Definition**: `/home/user/ducktape/prompts/scans/denormalized-computed-fields.md`

## Executive Summary

This scan identified **3 violations** of the denormalized/computed fields pattern across the codebase. These violations involve fields that are redundantly stored alongside data from which they can be computed, creating maintenance burden and consistency risks.

## Violation Details

### 1. HabitsResult: Redundant count field

**File**: `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py`
**Lines**: 173-177
**Severity**: Medium

#### Issue
```python
class HabitsResult(BaseModel):
    """Result for getHabits tool."""

    habits: list[Habit]
    count: int
```

**Problem**: The `count` field is redundantly stored when it's simply `len(habits)`. This is a direct computation from the items list.

**Rationale**:
- The count can always be computed by clients as `len(response.habits)`
- The field adds no information not already present in the items list
- When items are returned in full (not paginated), count is redundant

**Fix Strategy**:
1. Remove the `count` field from the model
2. Update code that constructs `HabitsResult` to not pass the count
3. Document that clients should use `len(habits)` to get the count

**Related Code Pattern** (from definition):
```python
# BAD: Both items and derived count
class ItemsResult(BaseModel):
    items: list[Item]
    total_count: int  # Just len(items)

# GOOD: Only items (unless paginated)
class ItemsResult(BaseModel):
    items: list[Item]  # Clients compute: count = len(items)
```

---

### 2. DateRangeStatusResult: Potentially redundant date_count field

**File**: `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py`
**Lines**: 200-206
**Severity**: Medium (requires domain review)

#### Issue
```python
class DateRangeStatusResult(BaseModel):
    """Result for getHabitStatus tool with date range."""

    statuses: list[DateRangeStatusItem]
    start_date: ISODate
    end_date: ISODate
    date_count: int
```

**Problem**: The `date_count` field appears to be derived from the date range and may be redundant if it always equals `len(statuses)` or can be computed from the date range bounds.

**Rationale**:
- If `date_count` always equals `len(statuses)`, it's redundant
- If it represents "total days in range" (days between start_date and end_date), it should be documented as distinct from the items count
- Ambiguity about what this field represents creates maintenance burden

**Recommended Review**:
1. Confirm whether `date_count` always equals `len(statuses)`
2. If yes, remove it and let clients compute from the list
3. If no, clarify the semantic meaning and document the difference
4. Consider renaming to `total_days_in_range` for clarity if it represents computed days

---

### 3. ShellCommandResult: Derived timed_out boolean field

**File**: `/home/user/ducktape/ember/src/ember/tools/run_shell_command.py`
**Lines**: 18-23
**Severity**: Low-Medium

#### Issue
```python
class ShellCommandResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
```

**Problem**: The `timed_out` field is derived from `exit_code`. Looking at the implementation (line 50), when a timeout occurs, the exit code is explicitly set to 124, making the `timed_out` field redundant.

**Current Code Pattern** (lines 49-51):
```python
return ShellCommandResult(
    exit_code=124, stdout=_decode_stream(stdout),
    stderr=_decode_stream(stderr), timed_out=True
)
```

**Rationale**:
- The relationship between `exit_code=124` and `timed_out=True` is implicit and must be documented
- Clients must either know the magic number 124 or refer to `timed_out`
- Storing both duplicates information about the same state

**Fix Strategy**:
1. **Option A (Recommended)**: Remove `timed_out` field and document that exit code 124 indicates timeout
2. **Option B**: Use a discriminated union to make timeout state explicit:
   ```python
   class TimeoutResult(BaseModel):
       kind: Literal["timeout"] = "timeout"
       stdout: str
       stderr: str

   class SuccessResult(BaseModel):
       kind: Literal["success"] = "success"
       exit_code: int
       stdout: str
       stderr: str

   ShellCommandResult = Annotated[TimeoutResult | SuccessResult, Field(discriminator="kind")]
   ```

**Client Impact**:
- Current: `if result.timed_out: ...`
- After (Option A): `if result.exit_code == 124: ...` (or document the constant)
- After (Option B): `if isinstance(result, TimeoutResult): ...` (explicit and type-safe)

---

## Scan Methodology

The scan used the following detection strategies:

1. **Pattern Matching**: Searched for common denormalized patterns:
   - Boolean fields paired with enum/status fields
   - `count`/`total_count` fields alongside list fields
   - `formatted_*` fields alongside date fields

2. **Manual Code Review**: Examined BaseModel class definitions across the codebase to identify semantic relationships between fields

3. **Cross-Reference Check**: Verified where these models are constructed to confirm the computed nature of fields

## Fields That Correctly Use Computed Patterns (No Violations)

### PRStatus enum (github_models.py, lines 14-45)
**Status**: OK - Properly uses `@property` for computed values

Properties like `is_merged`, `is_open`, `is_closed`, and `display_text` are correctly implemented as computed properties (not stored fields). These provide convenient derived values without creating denormalization issues.

### StatusResult properties (protocol.py, lines 243-251)
**Status**: OK - Properly uses `@property` for computed values

Properties `has_dirty_files` and `has_untracked_files` are computed on-demand from their respective count fields, which is the correct pattern for derived booleans.

---

## Summary Table

| Violation | File | Type | Status | Impact |
|-----------|------|------|--------|--------|
| HabitsResult.count | habitify_mcp_server/types.py:173 | Redundant field | NEEDS_FIX | Small API reduction, client simplification |
| DateRangeStatusResult.date_count | habitify_mcp_server/types.py:200 | Ambiguous field | NEEDS_REVIEW | Unclear semantics, maintenance burden |
| ShellCommandResult.timed_out | ember/.../run_shell_command.py:18 | Derived field | NEEDS_FIX | Implicit exit code magic number |

---

## Recommendations

### High Priority
1. **Remove HabitsResult.count** - This is a clear redundancy with no ambiguity
2. **Fix ShellCommandResult.timed_out** - Either remove (Option A) or restructure with discriminated union (Option B)

### Medium Priority
3. **Clarify DateRangeStatusResult.date_count** - Determine semantic meaning and document or remove

### Best Practices Going Forward
1. When designing response models, ask: "Is this field derivable from other fields in the response?"
2. If yes, and it's not providing information hidden from clients (like paginated total counts), remove it
3. Use `@property` methods for convenience computations that don't need to be persisted
4. Use Pydantic `computed_fields` only when computation is expensive or requires server-side data unavailable to clients
5. Document any implicit contracts (like exit code 124 = timeout) clearly

---

## References

- Scan Definition: `/home/user/ducktape/prompts/scans/denormalized-computed-fields.md`
- Related: [Pydantic Computed Fields](https://docs.pydantic.dev/latest/concepts/computed_fields/)
- API Design: [Avoid Denormalization](https://apisyouwonthate.com/blog/guessing-api-http-status-codes)
