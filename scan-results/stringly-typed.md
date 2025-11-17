# Stringly-Typed Code Scan Results

## Summary

This scan identified multiple instances of stringly-typed code across the ducktape codebase where raw strings are used for categorical values instead of enums (particularly `StrEnum`). The codebase already uses `StrEnum` in some areas (e.g., `ResponseStatus`, `Status` in habitify), but many other areas still use plain strings with hardcoded comparisons.

**Total categories of findings:** 7 major areas
**Update 2025-11-17:** Finding #1 fully applied. Remaining: 6 findings.

**Severity:** Medium - These patterns reduce type safety, make refactoring harder, and are prone to typos

## Detailed Findings

### ~~1. rspcache: Inconsistent Status Type Usage~~ ✅ FULLY APPLIED

**Status**: Fully fixed - enum expanded and used consistently throughout

**What was applied:**
- ✅ `ResponseStatus` enum expanded to: `QUEUED`, `IN_PROGRESS`, `COMPLETE`, `ERROR`
- ✅ `ResponseStatusEvent.status` field now typed as `ResponseStatus`
- ✅ All string literals replaced with enum values (including final fix at `__init__.py:276`)

---

### 2. habitify MCP: CLI Accepts Strings Instead of Enums

**Location:** `/home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/`

**Issue:** The types module properly defines `Status` enum, but the CLI still accepts raw strings.

**Evidence:**

#### Good: Enum exists
```python
# /home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py:30-37
class Status(str, Enum):
    """Valid habit status values."""
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    NONE = "none"
    IN_PROGRESS = "in_progress"
```

#### Bad: CLI accepts string, not enum
```python
# /home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/cli.py:280
status: str = typer.Option("completed", "--status", "-s",
    help="Status to set (completed, skipped, failed, none)"),

# Line 295
status: str,
```

**Issue:** Typo-prone - user could pass "complet" and it would be accepted at CLI level

**Recommendation:** Change to `status: Status` and let Typer handle enum validation

#### Bad: API method accepts string
```python
# /home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/habitify_client.py:179
status: str | None = None,
```

**Recommendation:** Change to `status: Status | None = None`

#### Bad: Untyped string fields in Habit model
```python
# /home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/types.py:113-114
log_method: str = ""
recurrence: str
priority: str | None = None  # Line 78
```

**Issue:** These appear to have limited valid values but are typed as plain strings

**Recommendation:** If the API has a fixed set of values for these fields, create enums:
- `LogMethod` enum
- `Recurrence` enum
- `Priority` enum

---

### 3. claude_optimizer: Test Status Literals

**Location:** `/home/user/ducktape/claude/claude_optimizer/`

**Issue:** Tests use string literals for status instead of an enum.

**Evidence:**

```python
# /home/user/ducktape/claude/claude_optimizer/tests/test_optimizer.py:215
status="completed",

# /home/user/ducktape/claude/claude_optimizer/tests/test_optimizer.py:223
status="completed",

# /home/user/ducktape/claude/claude_optimizer/tests/test_e2e_database.py:172
status="running",

# /home/user/ducktape/claude/claude_optimizer/tests/test_e2e_database.py:181
assert retrieved_run.status == "running"

# /home/user/ducktape/claude/claude_optimizer/tests/test_full_e2e_workflow.py:666
run.status = "completed"

# /home/user/ducktape/claude/claude_optimizer/tests/test_full_e2e_workflow.py:673
assert run.status == "completed"
```

**Recommendation:** Create `OptimizationRunStatus` enum with values like `RUNNING`, `COMPLETED`, `FAILED`

---

### 4. claude-history: Multiple Type Fields

**Location:** `/home/user/ducktape/experimental/claude-history/claude_history_reader.py`

**Issue:** Multiple models have untyped `type` fields used for discriminating variants.

**Evidence:**

```python
# Line 29
class TextContent(BaseModel):
    type: str  # ❌ Should be Literal or enum

# Line 41
type: str | None = None  # ❌ Optional type field

# Line 53
type: str = "summary"  # ❌ Should be Literal["summary"]

# Line 67, 77, 128
type: str  # ❌ Multiple models with plain type fields
```

**Issue:** When `type` is used for discrimination in a union, it should be `Literal[...]` for each variant

**Recommendation:**
1. For `SummaryEntry`, use `type: Literal["summary"] = "summary"`
2. For discriminated unions, use Pydantic's `Field(discriminator="type")` with Literal tags
3. If types form a closed set across all messages, create a `MessageType` enum

---

### 5. inop/engine: Environment Type Strings

**Location:** `/home/user/ducktape/adgn/src/adgn/inop/engine/models.py`

**Issue:** `RunnerEnvironment.type` is a plain string with hardcoded comparisons.

**Evidence:**

```python
# Line 221
type: str = "coding"  # Default to coding for backwards compatibility

# Line 342
type: str  # "docker_container", "workspace_dir", etc.

# Line 348
if self.type == "docker_container":

# Line 355
if self.type == "workspace_dir":
```

**Also in grading/strategies.py:**
```python
# /home/user/ducktape/adgn/src/adgn/inop/grading/strategies.py:79
if context.environment.type == "docker_container":

# Line 84
elif context.environment.type == "workspace_dir":
```

**Recommendation:** Create enums:
```python
class TaskTypeEnum(StrEnum):
    CODING = "coding"
    # ... other types

class EnvironmentType(StrEnum):
    DOCKER_CONTAINER = "docker_container"
    WORKSPACE_DIR = "workspace_dir"
```

---

### 6. Unstructured Error Messages

**Location:** Multiple files across the codebase

**Issue:** Error fields are free-form strings with no categorization.

**Evidence:**

```python
# /home/user/ducktape/adgn/src/adgn/rspcache/events.py:20
error: str | None = None

# /home/user/ducktape/adgn/src/adgn/rspcache/admin_app.py:82
error: str | None = None

# /home/user/ducktape/adgn/src/adgn/inop/engine/models.py:277
error: str | None = None

# /home/user/ducktape/adgn/src/adgn/inop/engine/models.py:324
error_message: str | None = None

# /home/user/ducktape/wt/src/wt/shared/protocol.py:203
error: str

# /home/user/ducktape/wt/src/wt/shared/protocol.py:301
error: str | None = None

# /home/user/ducktape/claude/claude_optimizer/graders/scoresheet.py:69
error_message: str  # Empty string if no error, actual message if error occurred
```

**Issue:** These error messages are unstructured, making it hard to:
- Categorize errors for metrics/alerting
- Handle different error types programmatically
- Query/filter errors in logs or databases

**Recommendation:** Use structured error types with enum-based categorization:

```python
class ErrorType(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    # etc.

class StructuredError(BaseModel):
    type: ErrorType
    message: str
    detail: dict[str, Any] | None = None
```

Or use discriminated unions for type-specific error fields:
```python
class ValidationError(BaseModel):
    type: Literal["validation_error"]
    field: str
    message: str

class NetworkError(BaseModel):
    type: Literal["network_error"]
    status_code: int | None = None
    message: str

Error = ValidationError | NetworkError | ...
```

---

### 7. openai_utils/probe: Type/Kind Strings

**Location:** `/home/user/ducktape/adgn/src/adgn/openai_utils/probe/main.py`

**Issue:** `ProbeKind` exists as a Literal type but fields use plain strings.

**Evidence:**

```python
# Line 108
type: str | None = None  # ❌ Should use an enum if type has fixed values

# Line 282
type: str = "event"  # ❌ Should be Literal["event"]

# Line 286
kind: str  # ❌ Should use ProbeKind enum

# Line 129 - Good example
ProbeKind = Literal["responses", "chat"]  # ✓ But should be StrEnum for reusability

# Usage with string comparisons:
# Line 183
if res.kind == "chat":

# Line 187
elif res.kind == "responses":
```

**Recommendation:** Convert `ProbeKind` from Literal to StrEnum:
```python
class ProbeKind(StrEnum):
    RESPONSES = "responses"
    CHAT = "chat"
```

And use it in the model:
```python
kind: ProbeKind
```

---

## Patterns with Good Enum Usage (For Reference)

The codebase already has good examples of StrEnum usage:

1. **wt (worktree tool)** - Extensive enum usage:
   - `StrategyType`, `RepositoryState`, `DaemonHealthStatus`, `StartupPhase`, `StreamEventType`, `ProgressOperation`, `WorktreeCreateStep`, `HookStream`, `ComponentState`, `GitstatusdState`, `CowMethod`, `PRStatus`, `PRState`, `PRMergeability`

2. **adgn/rspcache** - `ResponseStatus` (though underused)

3. **adgn/inop** - `AgentTaskType`

4. **adgn/seatbelt** - `Action`, `FileOp`, `NetworkOp`, `DefaultBehavior`, `EnvPassthroughMode`

5. **adgn/git_commit_ai** - `TaskStatus`

6. **adgn/openai_utils** - `ReasoningEffort`, `ReasoningSummary`, `Family`, `ErrorCode`

7. **habitify** - `Status`, `UnitType`, `Periodicity`

---

## Literal Types That Could Be StrEnum

The codebase uses many `Literal[...]` types. While Literals are good for single-use type constraints, some appear multiple times and would benefit from being StrEnum:

```python
# /home/user/ducktape/adgn/src/adgn/rspcache/admin_app.py:81
status: Literal["completed", "failed", "in_progress", "cancelled", "queued", "incomplete"] | None

# /home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/habitify_client.py:316
status: Literal["completed", "skipped", "failed", "none"]

# /home/user/ducktape/adgn/src/adgn/openai_utils/probe/main.py:129
ProbeKind = Literal["responses", "chat"]
```

**Recommendation:** Convert these to StrEnum when:
1. The same literal set is used in multiple places
2. You need to enumerate all values programmatically
3. The values might be extended in the future

---

## Migration Priority

**High Priority (Most Impact):**
1. **rspcache status handling** - Expand `ResponseStatus` enum and use it consistently
2. **inop environment types** - Create `EnvironmentType` enum
3. **habitify CLI** - Use `Status` enum instead of strings

**Medium Priority:**
1. **claude_optimizer status** - Create `OptimizationRunStatus` enum
2. **openai_utils probe kinds** - Convert Literal to StrEnum
3. **Structured errors** - Start with most common error sites (rspcache, wt)

**Low Priority (Can be done incrementally):**
1. **claude-history types** - Add Literal discriminators
2. **habitify field enums** - Add enums for log_method, recurrence if API supports it

---

## Benefits of Fixing These Issues

1. **Type Safety** - Typos caught at type-check time (e.g., "complet" vs "complete")
2. **IDE Support** - Autocomplete shows all valid values
3. **Documentation** - Enum definition documents all possible states
4. **Refactoring** - Rename enum value, all usages update automatically
5. **Exhaustiveness** - Type checker can ensure all cases are handled
6. **Structured Error Handling** - Categorize and query errors programmatically

---

## Example Fix (rspcache)

**Before:**
```python
# events.py
class ResponseStatusEvent(EventBase):
    status: str

# responses_db.py
status="queued"
if cached.status == "complete":

# admin_app.py
status: Literal["completed", "failed", "in_progress", ...] | None
```

**After:**
```python
# models.py
class ResponseStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"

# events.py
class ResponseStatusEvent(EventBase):
    status: ResponseStatus

# responses_db.py
status=ResponseStatus.QUEUED
if cached.status == ResponseStatus.COMPLETE:

# admin_app.py
status: ResponseStatus | None = None
```

**Benefits:**
- Type checker catches `status="complet"` typo
- IDE autocompletes `ResponseStatus.`
- Single source of truth for all valid statuses
- Easy to add new status values
