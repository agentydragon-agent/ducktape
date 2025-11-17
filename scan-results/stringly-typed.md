# Stringly-Typed Code Scan Results

## Summary

This scan identified multiple instances of stringly-typed code across the ducktape codebase where raw strings are used for categorical values instead of enums (particularly `StrEnum`). The codebase already uses `StrEnum` in some areas (e.g., `ResponseStatus`, `Status` in habitify), but many other areas still use plain strings with hardcoded comparisons.

**Total categories of findings:** 7 major areas
**Update 2025-11-17:** Findings #1, #2 (CLI/API), #3, #5, #7 fully applied. Remaining: 2 findings (#4, #6).

**Severity:** Medium - These patterns reduce type safety, make refactoring harder, and are prone to typos

## Detailed Findings

### ~~1. rspcache: Inconsistent Status Type Usage~~ ✅ FULLY APPLIED

**Status**: Fully fixed - enum expanded and used consistently throughout

**What was applied:**
- ✅ `ResponseStatus` enum expanded to: `QUEUED`, `IN_PROGRESS`, `COMPLETE`, `ERROR`
- ✅ `ResponseStatusEvent.status` field now typed as `ResponseStatus`
- ✅ All string literals replaced with enum values (including final fix at `__init__.py:276`)

---

### ~~2. habitify MCP: CLI Accepts Strings Instead of Enums~~ ✅ FULLY APPLIED

**Status**: Fixed - CLI and API methods now accept `Status` enum

**What was applied:**
- ✅ CLI `log` command now accepts `Status` enum instead of `str` (cli.py:281)
- ✅ `get_journal()` API method parameter changed from `status: str | None` to `status: Status | None` (habitify_client.py:179)
- ❌ Additional enums for `log_method`, `recurrence`, `priority` fields not created (API values unknown)

---

### ~~3. claude_optimizer: Test Status Literals~~ ✅ FULLY APPLIED

**Status**: Fixed - Created `OptimizationRunStatus` enum and updated tests

**What was applied:**
- ✅ Created `OptimizationRunStatus` enum in `tests/test_types.py` with values: `RUNNING`, `COMPLETED`, `FAILED`
- ✅ Updated `test_e2e_database.py` to use enum values (line 174, 183)
- ✅ Updated `test_full_e2e_workflow.py` to use enum values (line 668, 675)

---

### 4. claude-history: Multiple Type Fields

**Location:** `/home/user/ducktape/experimental/claude-history/claude_history_reader.py`

**Status:** NOT YET APPLIED - Consider using Literal discriminators (Anthropic SDK pattern)

**Context:** This parses Claude Code's internal history logs from `~/.claude/projects/`, NOT direct Anthropic API responses. Format is based on/similar to Anthropic Messages API but with extensions (e.g., "summary" entry type).

**Issue:** Multiple models have untyped `type` fields used for discriminating variants.

**Evidence:**

```python
# Line 29 - Content type discriminator
class TextContent(BaseModel):
    type: str  # ❌ Should be Literal["text"] | Literal["tool_use"] | Literal["tool_result"]

# Line 41 - Message type field
type: str | None = None  # ❌ Should be typed

# Line 53 - Custom entry type for Claude Code logs
type: str = "summary"  # ❌ Should be Literal["summary"] = "summary"

# Line 67 - Entry type discriminator
class MessageEntry(BaseModel):
    type: str  # ❌ Should be Literal["user"] | Literal["assistant"]

# Line 77 - Parsed message type
class ParsedMessage(BaseModel):
    type: str  # ❌ Should be Literal["user"] | Literal["assistant"]
```

**Anthropic SDK Reference:**
The official Anthropic SDK uses proper Literal discriminators for similar structures:
```python
# From anthropic.types
class TextBlock(BaseModel):
    type: Literal["text"]
    text: str

class ToolUseBlock(BaseModel):
    type: Literal["tool_use"]
    id: str
    name: str
    input: Dict[str, object]

# Param type (input to API)
class ToolResultBlockParam(TypedDict):
    type: Required[Literal["tool_result"]]
    tool_use_id: Required[str]
    content: Union[str, Iterable[Content]]
    is_error: bool
```

**Recommendation:**
Since claude-history parses Claude Code's extended format (not direct API):

1. **Option A: Use Literal discriminators (like Anthropic SDK)**:
   ```python
   class SummaryEntry(BaseModel):
       type: Literal["summary"] = "summary"  # Custom to Claude Code logs
       summary: str
       leaf_uuid: str

   class TextContent(BaseModel):
       type: Literal["text"]
       text: str | None = None

   class ParsedMessage(BaseModel):
       type: Literal["user", "assistant"]  # Like SDK's MessageParam role
       # ...
   ```

2. **Option B: Skip** - This is experimental code in `experimental/` directory. May be acceptable to leave as-is if it's just exploratory tooling.

**Decision:** Recommend Option B (skip) - experimental code, internal format parsing. Not worth the effort unless this becomes production tooling.

---

### ~~5. inop/engine: Environment Type Strings~~ ✅ FULLY APPLIED

**Status**: Fixed - Created enums and updated all usages

**What was applied:**
- ✅ Created `TaskTypeEnum` enum with value `CODING`
- ✅ Created `EnvironmentType` enum with values: `DOCKER_CONTAINER`, `WORKSPACE_DIR`
- ✅ Updated `TaskDefinition.type` to use `TaskTypeEnum`
- ✅ Updated `RunnerEnvironment.type` to use `EnvironmentType`
- ✅ Replaced all string comparisons in `models.py` and `grading/strategies.py` with enum values
- ✅ Changed `pass` to `raise NotImplementedError` in unimplemented Docker container branch

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

### ~~7. openai_utils/probe: Type/Kind Strings~~ ✅ FULLY APPLIED

**Status**: Fixed - Converted `ProbeKind` from Literal to StrEnum and updated all usages

**What was applied:**
- ✅ Converted `ProbeKind` from `Literal["responses", "chat"]` to StrEnum with values: `RESPONSES`, `CHAT`
- ✅ Replaced all string comparisons (`kind == "chat"`, `kind == "responses"`) with enum values
- ✅ Updated 9 locations across the file (lines 188, 192, 467, 471, 507, 511, 545, 551, 572, 577, 623)

---

## Patterns with Good Enum Usage (For Reference)

The codebase has many examples of StrEnum usage:

1. **wt (worktree tool)** - Extensive enum usage:
   - `StrategyType`, `RepositoryState`, `DaemonHealthStatus`, `StartupPhase`, `StreamEventType`, `ProgressOperation`, `WorktreeCreateStep`, `HookStream`, `ComponentState`, `GitstatusdState`, `CowMethod`, `PRStatus`, `PRState`, `PRMergeability`

2. **adgn/rspcache** - `ResponseStatus` (now fully used throughout)

3. **adgn/inop** - `AgentTaskType`, `TaskTypeEnum`, `EnvironmentType`

4. **adgn/seatbelt** - `Action`, `FileOp`, `NetworkOp`, `DefaultBehavior`, `EnvPassthroughMode`

5. **adgn/git_commit_ai** - `TaskStatus`

6. **adgn/openai_utils** - `ReasoningEffort`, `ReasoningSummary`, `Family`, `ErrorCode`, `ProbeKind`

7. **habitify** - `Status`, `UnitType`, `Periodicity`

8. **claude_optimizer** - `OptimizationRunStatus` (tests)

---

## Remaining Work

Two findings remain unaddressed:

1. **Finding #4: claude-history types** - **RECOMMEND SKIP**
   - Experimental code parsing Claude Code's internal logs (not production)
   - Could use Literal discriminators like Anthropic SDK, but not worth effort for exploratory tooling
   - If this becomes production code, apply Literal types following Anthropic SDK patterns

2. **Finding #6: Unstructured errors** - **RECOMMEND SKIP**
   - Large architectural change affecting multiple systems
   - Would require careful design of error taxonomy
   - Would require migration strategy across rspcache, inop, wt, claude_optimizer
   - Not worth effort unless error categorization becomes critical business need

---

## Benefits of StrEnum Migration

1. **Type Safety** - Typos caught at type-check time (e.g., "complet" vs "complete")
2. **IDE Support** - Autocomplete shows all valid values
3. **Documentation** - Enum definition documents all possible states
4. **Refactoring** - Rename enum value, all usages update automatically
5. **Exhaustiveness** - Type checker can ensure all cases are handled
6. **Structured Error Handling** - Categorize and query errors programmatically
