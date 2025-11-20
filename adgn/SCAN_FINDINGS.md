# Code Quality Scan Findings - adgn/agent

**Scan Date**: 2025-11-20
**Scope**: `adgn/src/adgn/agent/` and `adgn/tests/agent/`
**Scans Run**: 7 parallel scans

---

## Executive Summary

| Scan | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| Vulture (Dead Code) | 0 | 0 | 2 | 68 | 2 actionable |
| Stringly-Typed | 2 | 0 | 3 | 0 | 5 |
| Test Assertions | 0 | 110 | 19 | 3 | 132 |
| Useless Documentation | 0 | 0 | 146 | 0 | 146 |
| Pydantic Antipatterns | 0 | 1 | 7 | 0 | 8 |
| Overly Loose Typing | 0 | 10 | 13 | 2 | 25 |
| Code Duplication | 0 | 3 | 2 | 3 | 8 |
| **TOTAL** | **2** | **124** | **192** | **76** | **326** |

---

## 1. Vulture: Dead/Unused Code

### Actionable Findings (2)

**HIGH CONFIDENCE - Remove These Imports:**

1. **`/adgn/src/adgn/agent/persist/sqlite.py:33`**
   ```python
   # Remove: ChatMessage, ChatLastRead (unused in this file)
   from .models import Agent, Run, Event, ToolCall as ToolCallModel, Policy, Base
   ```

2. **`/adgn/src/adgn/agent/persist/models.py:12`**
   ```python
   # Remove: Boolean (imported but never used)
   from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, text
   ```

**False Positives to Ignore (68):**
- FastAPI exception handlers (called via decorators)
- FastAPI route handlers (called via framework)
- FastMCP tools (called via `@mcp.tool()`)
- Pydantic `model_config` attributes
- SQLAlchemy relationships
- Pytest fixtures (dependency injection)

---

## 2. Stringly-Typed Code

### Critical Issues (2)

**1. Policy Status Hardcoded Strings (7 locations)**
- `/adgn/src/adgn/agent/persist/sqlite.py:195,210,211,217,306,307,311`
- String literals: `"ACTIVE"`, `"SUPERSEDED"`
- **Fix**: Create `PolicyStatus` enum

**2. Duplicate RunStatus Enums (2 locations)**
- `/adgn/src/adgn/agent/persist/__init__.py:33-37` (4 values)
- `/adgn/src/adgn/agent/server/protocol.py:80-87` (7 values)
- **Issue**: Incompatible enums for same concept
- **Fix**: Clarify semantic difference or consolidate

### Medium Issues (3)

3. **ApprovalKind Literal** (`/adgn/src/adgn/agent/server/state.py:39`)
   - Uses `Literal["approve", "deny_continue", "deny_abort"]` instead of enum
   - **Fix**: Create `UserApprovalDecision` enum

4. **Database Schema Type Mismatches**
   - `/adgn/src/adgn/agent/persist/models.py:61,90,152`
   - Columns typed as `str` with comments indicating enums
   - **Fix**: Align type annotations with enum usage

5. **ProposalStatus Inconsistency**
   - Mixed enum/string usage in persistence layer
   - **Fix**: Standardize on enum usage

---

## 3. Test Assertions

### High Priority (110 occurrences)

**1. isinstance() → instance_of() (55 occurrences)**
```python
# BEFORE
assert isinstance(dec, Continue)

# AFTER
from hamcrest import assert_that, instance_of
assert_that(dec, instance_of(Continue))
```

**2. len() → has_length() (55 occurrences)**
```python
# BEFORE
assert len(items) == 1

# AFTER
from hamcrest import assert_that, has_length
assert_that(items, has_length(1))
```

### Medium Priority (19 occurrences)

3. **String 'in' → contains_string()** (15+ occurrences)
4. **any() comprehensions → has_item()** (6+ occurrences)
5. **getattr() probing** (4 occurrences) - use direct access or `has_properties()`

### Low Priority (3 occurrences)

6. **Bare variable assertions** (2) - add error messages
7. **Type name assertions** (1) - use `instance_of()` instead of `type(obj).__name__`

---

## 4. Useless Documentation

### Summary: 146 Obvious Comments

**Pattern**: Comments that merely restate code

**Top Offenders:**
- `test_agents_server.py` - 28 instances
- `test_sqlite_tool_calls.py` - 11 instances
- `test_mcp_ui.py` - 11 instances
- `mcp_bridge/server.py` - 7 instances
- `runtime/infrastructure.py` - 6 instances

**Examples to Remove:**
```python
# Create completed tool call record  ← DELETE
record = ToolCallRecord(...)

# Get pending approvals count  ← DELETE
count = len(pending)

# Parse Bearer token  ← DELETE
parts = auth_header.split()
```

**Keep Comments That Explain:**
- Workarounds for bugs
- Non-obvious ordering requirements
- Performance implications
- Rationale for design choices

---

## 5. Pydantic Antipatterns

### High Priority (1)

**1. Untyped dict Field**
- `/adgn/src/adgn/agent/mcp_bridge/servers/agents.py:194`
```python
# BEFORE
policy: dict  # Contains: content, id, proposals

# AFTER
policy: dict[str, Any]  # OR create PolicyStateContent model
```

### Medium Priority (7)

2. **Missing Field Descriptions** (7+ models)
   - `GroundTruthUsage`, `ToolCall`, `AgentPreset`, `ToolItem`, `PolicyError`, etc.
   - **Fix**: Add `Field(description=...)`

3. **Any-Typed Field**
   - `/adgn/src/adgn/agent/persist/events.py:39`
   ```python
   content: Any | None = None  # Should be JsonValue | None
   ```

4. **dict[str, Any] Internal Usage** (11 occurrences)
   - Most at I/O boundaries (acceptable)
   - Some internal functions could use typed models

---

## 6. Overly Loose Typing

### High Priority (10)

**1. Any-Typed Parameters (5)**
- `/adgn/src/adgn/agent/transcript_handler.py:49` - `_write_event(evt: Any)`
- `/adgn/src/adgn/agent/transcript_handler.py:76` - `on_response(evt: Any)`
- `/adgn/src/adgn/agent/persist/handler.py:33` - `_spawn(coro: Any)`
- **Fix**: Replace with proper types

**2. Any-Typed Variables (4)**
- `/adgn/src/adgn/agent/event_renderer.py:74` - `parsed: Any | None`
- `/adgn/src/adgn/agent/server/state.py:46,56` - `args: Any | None`
- **Fix**: Replace with specific JSON types or models

**3. Any in ResponsePayload (1)**
- `/adgn/src/adgn/agent/persist/events.py:39` - `content: Any | None`
- **Fix**: Use `JsonValue | None`

### Medium Priority (13)

**4. dict[str, Any] Parameters (8)**
- `/adgn/src/adgn/agent/server/runtime.py:119,184` - `send_json(payload: dict[str, Any])`
  - **Fix**: Use `ServerMessage` type
- `/adgn/src/adgn/agent/persist/handler.py:79` - `payload: dict[str, Any]`
  - **Fix**: Use `TypedPayload` discriminated union

**5. object Parameters (3)**
- `/adgn/src/adgn/agent/event_renderer.py:101,139,156`
- **Fix**: Replace with specific JSON type unions

**6. Type Aliases (2)**
- `ToolMap = dict[str, Any]` - should document structure
- `JsonlRecord = dict[str, Any]` - acceptable but document

---

## 7. Code Duplication

### High Priority (3 patterns, ~80 occurrences)

**1. UI Page Navigation (32 occurrences)**
- **Status**: Helper already exists (`e2e_open_agent_page()`)
- **Action**: Migrate all E2E tests to use helper
- Files: `test_abort.py`, `test_approvals.py`, `test_mcp_*.py`

**2. Send Prompt Pattern (30 occurrences)**
```python
# Extract to: send_prompt(page, text)
page.locator('textarea[placeholder^="Type a prompt"]').fill(text)
page.get_by_role("button", name="Send").click()
```

**3. Echo MCP Attachment (19 occurrences)**
```python
# Extract to: attach_echo_mcp(base_url, agent_id)
spec = {"echo": {"transport": "inproc", "factory": "..."}}
patch = requests.patch(base + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
```

### Medium Priority (2 patterns, ~30 occurrences)

**4. Pending Approvals Wait (19 occurrences)**
- Extract to: `wait_for_pending_approvals(page, count)`

**5. Approve Button Click (11 occurrences)**
- Extract to: `approve_first_pending(page)`

### Low Priority (3 patterns)

6. **Responses State Machine** (21 occurrences) - parametrizable factories
7. **End-Turn Tool Call** (33 occurrences) - helper fixture
8. **Agent Creation + MCP** (19 occurrences) - combined wrapper

---

# CLEANUP PLAN

## Phase 1: Quick Wins (Low Effort, High Impact)

**Estimated Time: 2-4 hours**

### 1.1 Remove Dead Imports
- [ ] `/adgn/src/adgn/agent/persist/sqlite.py:33` - Remove `ChatMessage`, `ChatLastRead`
- [ ] `/adgn/src/adgn/agent/persist/models.py:12` - Remove `Boolean`
- Run tests to verify

### 1.2 Remove Useless Comments (146 instances)
- [ ] Target test files first (108 instances)
  - `test_agents_server.py` (28)
  - `test_sqlite_tool_calls.py` (11)
  - `test_mcp_ui.py` (11)
- [ ] Source files (38 instances)
  - `mcp_bridge/server.py` (7)
  - `infrastructure.py` (6)
- Pattern: Remove `# Create/Get/Parse/Check` comments for trivial operations
- Keep comments explaining "why", not "what"

### 1.3 Extract E2E Test Helpers
- [ ] Extract `send_prompt(page, text)` helper
- [ ] Extract `attach_echo_mcp(base_url, agent_id)` helper
- [ ] Extract `wait_for_pending_approvals(page, count)` helper
- [ ] Extract `approve_first_pending(page)` helper
- [ ] Migrate E2E tests to use `e2e_open_agent_page()` (already exists)

---

## Phase 2: Type Safety (Medium Effort, High Value)

**Estimated Time: 4-8 hours**

### 2.1 Fix Stringly-Typed Code (Critical)
- [ ] Create `PolicyStatus` enum
  ```python
  class PolicyStatus(StrEnum):
      ACTIVE = "active"
      SUPERSEDED = "superseded"
      PROPOSED = "proposed"
      REJECTED = "rejected"
  ```
- [ ] Replace 7 hardcoded string literals in `sqlite.py`
- [ ] Resolve `RunStatus` duplication (clarify/consolidate)
- [ ] Create `UserApprovalDecision` enum (replace `ApprovalKind` Literal)

### 2.2 Tighten Loose Typing (High Priority)
- [ ] Fix `transcript_handler.py:49` - `evt: Any` → proper union
- [ ] Fix `event_renderer.py:74` - `_parse_json_or_none()` return type
- [ ] Fix `server/runtime.py:119,184` - `payload: dict[str, Any]` → `ServerMessage`
- [ ] Fix `persist/handler.py:79` - `payload: dict[str, Any]` → `TypedPayload`
- [ ] Fix `server/state.py:46,56` - `args: Any | None` → `dict[str, Any] | None`
- [ ] Fix `persist/events.py:39` - `content: Any | None` → `JsonValue | None`

### 2.3 Pydantic Improvements
- [ ] Type `AgentPolicyState.policy` field
- [ ] Add Field descriptions to 7+ models:
  - `GroundTruthUsage`
  - `ToolCall`
  - `AgentPreset`
  - `ToolItem`
  - `PolicyError`
  - `AgentBrief`

---

## Phase 3: Test Quality (Medium Effort, Medium Value)

**Estimated Time: 6-10 hours**

### 3.1 Migrate Test Assertions (High Impact)
- [ ] `isinstance()` → `instance_of()` (55 occurrences)
  - Semi-automated with regex replacement
- [ ] `len()` → `has_length()` (55 occurrences)
  - Semi-automated with regex replacement
- [ ] String `'in'` → `contains_string()` (15+ occurrences)
- [ ] `any()` comprehensions → `has_item()` (6+ occurrences)
- [ ] Remove `getattr()` probing (4 occurrences)
- [ ] Add error messages to bare assertions (2 occurrences)
- [ ] Fix type name assertion (1 occurrence)

---

## Phase 4: Refactoring (Higher Effort, Lower Priority)

**Estimated Time: 8-12 hours**

### 4.1 Extract Remaining Duplications
- [ ] Extract responses state machine factories (21 occurrences)
- [ ] Extract `make_ui_end_turn_response()` helper (33 occurrences)
- [ ] Extract `api_create_agent_with_echo_mcp()` wrapper (19 occurrences)

### 4.2 Database Schema Alignment
- [ ] Update ORM type annotations in `models.py` (3 fields)
- [ ] Standardize `ProposalStatus` enum usage

---

## Testing Strategy

After each phase:
1. Run full test suite: `pytest adgn/tests/agent`
2. Run type checker: `mypy adgn/src/adgn/agent`
3. Git diff review to ensure only intended changes
4. Commit with descriptive message referencing this plan

---

## Success Metrics

**Before:**
- 326 code quality issues identified
- 146 useless comments
- 110 weak test assertions
- 35 loose type annotations
- ~150 lines of duplicated E2E test code

**After Phase 1:**
- 2 dead imports removed
- 146 useless comments removed
- ~100 lines of E2E duplication eliminated

**After Phase 2:**
- 5 stringly-typed patterns fixed (enums introduced)
- 10 high-priority type looseness fixed
- 7+ models documented with Field descriptions

**After Phase 3:**
- 132 test assertions upgraded to PyHamcrest
- Better error messages on test failures
- More composable test code

**After Phase 4:**
- ~200 additional lines of duplication eliminated
- Fully typed event payloads
- Consistent database schema typing

---

## Maintenance

**Prevent Regression:**
1. Add pre-commit hook for comment detection (flag obvious patterns)
2. Configure mypy strict mode for new code
3. Document test assertion style guide (prefer PyHamcrest)
4. Add jscpd to CI (fail on high duplication scores)
5. Create scan documentation pattern for future sweeps
