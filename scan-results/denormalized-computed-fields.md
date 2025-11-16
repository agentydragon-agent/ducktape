# Scan Results: Denormalized and Computed Fields

## Summary

This scan identified **3 instances** of denormalized computed fields in the ducktape codebase where data structures store both canonical data and derived/computed values that could be calculated by clients.

All findings are in Pydantic BaseModel response classes where count fields are redundantly stored alongside the lists they count. These represent Pattern 3 from the scan prompt (Computed Aggregations).

## Findings

### 1. HabitsResult - Redundant count field

**File:** `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py`
**Lines:** 173-177

```python
class HabitsResult(BaseModel):
    """Result for getHabits tool."""

    habits: list[Habit]
    count: int
```

**Usage:** Line 71 in `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tools.py`
```python
return HabitsResult(habits=habits, count=len(habits))
```

**Why it matches:** The `count` field is set to `len(habits)` and provides no information beyond what clients can compute themselves. This is not a pagination scenario - all habits are returned in the response.

**Recommendation:** Remove the `count` field. Clients can compute `len(habits)` when needed.

---

### 2. DateRangeStatusResult - Redundant date_count field

**File:** `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py`
**Lines:** 200-206

```python
class DateRangeStatusResult(BaseModel):
    """Result for getHabitStatus tool with date range."""

    statuses: list[DateRangeStatusItem]
    start_date: ISODate
    end_date: ISODate
    date_count: int
```

**Usage:** Lines 208-213 in `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/tools.py`
```python
return DateRangeStatusResult(
    statuses=items,
    start_date=first_date or datetime.now().strftime("%Y-%m-%d"),
    end_date=last_date or datetime.now().strftime("%Y-%m-%d"),
    date_count=len(items),
)
```

**Why it matches:** The `date_count` field is set to `len(items)` and is redundant. All status items are returned in the response, so clients can compute the count.

**Recommendation:** Remove the `date_count` field. Clients can compute `len(statuses)` when needed.

---

### 3. TokenUsage - Redundant total field

**File:** `/home/user/ducktape/experimental/claude-history/claude_history_reader.py`
**Lines:** 99-106

```python
class TokenUsage(BaseModel):
    """Aggregated token usage statistics"""

    total_input: int = 0
    total_output: int = 0
    total_cache_creation: int = 0
    total_cache_read: int = 0
    total: int = 0
```

**Usage:** Lines 292-298 in the same file
```python
token_usage = TokenUsage(
    total_input=total_input_tokens,
    total_output=total_output_tokens,
    total_cache_creation=total_cache_creation_tokens,
    total_cache_read=total_cache_read_tokens,
    total=total_input_tokens + total_output_tokens,
)
```

**Why it matches:** The `total` field is computed as `total_input + total_output`, which clients can easily calculate. While it excludes cache tokens (possibly intentional), it still represents a simple arithmetic combination of existing fields.

**Recommendation:** Remove the `total` field. If clients need the sum of input and output tokens, they can compute it as `total_input + total_output`.

---

## Not Issues (False Positives)

### ErrorResponse.total_matches - Pagination pattern (acceptable)

**File:** `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py`
**Lines:** 164-170

This was initially flagged but is **NOT a denormalization issue**. The `matches` field contains only the first 5 matches (truncated), while `total_matches` provides the full count. This is the acceptable pagination pattern described in the scan prompt where the count provides information not available from the returned subset.

### @property decorators - Computed on access (acceptable)

Several Pydantic models use `@property` decorators (e.g., in `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py` lines 128-152). These compute values on-the-fly and are not stored fields, so they don't represent denormalization. This is actually the recommended pattern.

### formatted_date local variables - Display logic (acceptable)

The `formatted_date` variable in `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/cli.py` (lines 249, 326) is a local variable used for CLI display, not a stored field in a data model. This is acceptable presentation logic.

---

## Impact Summary

- **Response payload size:** Removing these 3 fields will reduce API response sizes slightly
- **Maintenance burden:** Eliminates need to keep computed fields in sync with source data
- **Client simplicity:** Modern clients (including LLMs) can easily compute these values
- **Breaking change:** This would be a breaking API change requiring version bump or deprecation period

## Recommendations

1. **Priority:** Medium - these are quality-of-life improvements rather than bugs
2. **Approach:** Deprecation path
   - Mark fields as deprecated in next minor version
   - Remove in next major version
   - Update API documentation to note that clients should compute these values
3. **Testing:** Ensure all client code is updated to compute values locally before removal
