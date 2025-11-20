# Parallel Agent Implementation Plan - Code Quality Fixes

**Source**: `adgn/SCAN_FINDINGS.md`
**Strategy**: Maximum parallelism with dependency awareness
**Target**: Phase 1 (Quick Wins) + Phase 2 (Type Safety)

---

## Execution Plan

### Wave 1: Independent Quick Wins (9 parallel agents)

These agents have **no dependencies** and can run simultaneously:

#### Agent 1: Remove Dead Imports
**Files**: 2 files
**Effort**: 5 minutes
**Task**:
- Remove `ChatMessage`, `ChatLastRead` from `/adgn/src/adgn/agent/persist/sqlite.py:33`
- Remove `Boolean` from `/adgn/src/adgn/agent/persist/models.py:12`
- Run tests to verify

#### Agent 2: Remove Useless Comments (Test Files - Batch 1)
**Files**: `test_agents_server.py` (28 comments)
**Effort**: 10 minutes
**Task**:
- Remove obvious `# Create/Get/Parse/Check` comments
- Keep "why" comments (workarounds, non-obvious behavior)
- Pattern: Delete trivial restatements

#### Agent 3: Remove Useless Comments (Test Files - Batch 2)
**Files**: `test_sqlite_tool_calls.py` (11), `test_mcp_ui.py` (11)
**Effort**: 10 minutes
**Task**: Same as Agent 2

#### Agent 4: Remove Useless Comments (Test Files - Batch 3)
**Files**: `test_mcp_performance.py` (8), `test_separated_servers.py` (7)
**Effort**: 10 minutes
**Task**: Same as Agent 2

#### Agent 5: Remove Useless Comments (Source Files)
**Files**: `mcp_bridge/server.py` (7), `infrastructure.py` (6), `cli.py` (5), others (20)
**Effort**: 15 minutes
**Task**: Same as Agent 2 for source files

#### Agent 6: Extract E2E Helper - send_prompt
**Files**: ~30 E2E test files
**Effort**: 20 minutes
**Task**:
- Add to `helpers.py`:
  ```python
  def send_prompt(page: Page, text: str) -> None:
      """Fill prompt textarea and click Send button."""
      page.locator('textarea[placeholder^="Type a prompt"]').fill(text)
      page.get_by_role("button", name="Send").click()
  ```
- Replace 30 occurrences with helper call

#### Agent 7: Extract E2E Helper - attach_echo_mcp
**Files**: ~19 E2E test files
**Effort**: 15 minutes
**Task**:
- Add to `helpers.py`:
  ```python
  def attach_echo_mcp(base_url: str, agent_id: str) -> None:
      """Attach echo MCP server to agent."""
      spec = {"echo": {"transport": "inproc", "factory": "adgn.mcp.testing.simple_servers:make_simple_mcp"}}
      patch = requests.patch(base_url + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
      assert patch.ok, patch.text
  ```
- Replace 19 occurrences

#### Agent 8: Extract E2E Helper - wait_for_pending_approvals
**Files**: ~19 E2E test files
**Effort**: 15 minutes
**Task**:
- Add to `helpers.py`:
  ```python
  def wait_for_pending_approvals(page: Page, count: int | None = None, timeout: int = 10000) -> None:
      """Wait for Pending Approvals indicator."""
      text = f"Pending Approvals ({count})" if count else "Pending Approvals"
      page.get_by_text(text).wait_for(timeout=timeout)
  ```
- Replace 19 occurrences

#### Agent 9: Extract E2E Helper - approve_first_pending
**Files**: ~11 E2E test files
**Effort**: 10 minutes
**Task**:
- Add to `helpers.py`:
  ```python
  def approve_first_pending(page: Page) -> None:
      """Click Approve button for first pending approval."""
      page.get_by_role("button", name="Approve").first.click()
  ```
- Replace 11 occurrences

---

### Wave 2: Type Safety Fixes (6 parallel agents)

**Dependency**: Wave 1 must complete first (to avoid merge conflicts in same files)

#### Agent 10: Create PolicyStatus Enum
**Files**: `persist/__init__.py` or new `persist/policy_types.py`, `persist/sqlite.py` (7 locations), `persist/models.py` (1)
**Effort**: 30 minutes
**Task**:
1. Create enum:
   ```python
   class PolicyStatus(StrEnum):
       ACTIVE = "active"
       SUPERSEDED = "superseded"
       PROPOSED = "proposed"
       REJECTED = "rejected"
   ```
2. Replace 7 hardcoded strings in `sqlite.py`
3. Update database schema comment in `models.py`

#### Agent 11: Resolve RunStatus Duplication
**Files**: `persist/__init__.py`, `server/protocol.py`
**Effort**: 30 minutes
**Task**:
1. Analyze semantic difference (persistence vs UI state)
2. Rename for clarity:
   - `InternalRunStatus` (persist layer: RUNNING, FINISHED, ERROR, ABORTED)
   - `UiRunStatus` (protocol layer: adds IDLE, STARTING, AWAITING_APPROVAL, ABORTING)
3. Add conversion function if needed
4. Update all references

#### Agent 12: Create UserApprovalDecision Enum
**Files**: `server/state.py`, `mcp_bridge/servers/agents.py`
**Effort**: 20 minutes
**Task**:
1. Create enum:
   ```python
   class UserApprovalDecision(StrEnum):
       APPROVE = "approve"
       DENY_CONTINUE = "deny_continue"
       DENY_ABORT = "deny_abort"
   ```
2. Replace `ApprovalKind` Literal
3. Update string comparisons to enum values

#### Agent 13: Tighten Loose Typing (High Priority Batch 1)
**Files**: `transcript_handler.py`, `event_renderer.py`
**Effort**: 30 minutes
**Task**:
1. Fix `transcript_handler.py:49` - `evt: Any` → proper union type
2. Fix `transcript_handler.py:76` - `on_response(evt: Any)` → `evt: Response`
3. Fix `event_renderer.py:74` - `_parse_json_or_none()` return `JsonValue | None`

#### Agent 14: Tighten Loose Typing (High Priority Batch 2)
**Files**: `server/runtime.py`, `persist/handler.py`, `server/state.py`
**Effort**: 30 minutes
**Task**:
1. Fix `server/runtime.py:119,184` - `payload: dict[str, Any]` → `ServerMessage`
2. Fix `persist/handler.py:79` - `payload: dict[str, Any]` → `TypedPayload`
3. Fix `server/state.py:46,56` - `args: Any | None` → `dict[str, Any] | None`
4. Fix `persist/events.py:39` - `content: Any | None` → `JsonValue | None`

#### Agent 15: Add Pydantic Field Descriptions
**Files**: Multiple model files
**Effort**: 25 minutes
**Task**:
Add `Field(description=...)` to 7+ models:
- `handler.py:23-29` - `GroundTruthUsage`
- `types.py:10-15` - `ToolCall`
- `presets.py:22-30` - `AgentPreset`
- `server/state.py:65-73` - `ToolItem`
- `models/policy_error.py:14-22` - `PolicyError`
- `mcp_bridge/servers/agents.py:36-40` - `AgentBrief`
- `mcp_bridge/servers/agents.py:194` - Type `AgentPolicyState.policy` field

---

### Wave 3: PyHamcrest Migration (10 parallel agents)

**Dependency**: Waves 1-2 must complete (avoid test file conflicts)

**Important**: Focus on **composable matchers**, not just simple replacements. Use `all_of()`, `has_properties()`, nested matchers from the updated scan prompt examples.

#### Agent 16: PyHamcrest - isinstance() Migration (Batch 1)
**Files**: Test files with 10-15 isinstance() calls
**Effort**: 20 minutes
**Task**:
- Migrate `isinstance()` → `instance_of()`
- **Combine with property checks** using `all_of()` when applicable:
  ```python
  # BEFORE
  assert isinstance(dec, Continue)
  assert dec.tool_policy.name == "auto"

  # AFTER
  assert_that(dec, all_of(
      instance_of(Continue),
      has_properties(tool_policy=has_properties(name="auto"))
  ))
  ```

#### Agent 17: PyHamcrest - isinstance() Migration (Batch 2)
**Files**: Test files with 10-15 isinstance() calls
**Effort**: 20 minutes
**Task**: Same as Agent 16

#### Agent 18: PyHamcrest - isinstance() Migration (Batch 3)
**Files**: Test files with 10-15 isinstance() calls
**Effort**: 20 minutes
**Task**: Same as Agent 16

#### Agent 19: PyHamcrest - isinstance() Migration (Batch 4)
**Files**: Remaining test files
**Effort**: 20 minutes
**Task**: Same as Agent 16

#### Agent 20: PyHamcrest - len() and Collection Assertions
**Files**: Test files with len() and collection operations
**Effort**: 30 minutes
**Task**:
- `len()` → `has_length()`
- `any()` comprehensions → `has_item()` with nested matchers
- Example from scan:
  ```python
  # BEFORE
  assert any(isinstance(it, FunctionCallItem) for it in items)

  # AFTER
  assert_that(items, has_item(instance_of(FunctionCallItem)))
  ```

#### Agent 21: PyHamcrest - String Assertions
**Files**: Test files with string operations (15+ occurrences)
**Effort**: 20 minutes
**Task**:
- `assert "x" in str` → `assert_that(str, contains_string("x"))`
- Combine multiple string checks with `all_of()`:
  ```python
  # BEFORE
  assert "Instructions" in text
  assert "MCP servers" in text
  assert "docker_exec" in text

  # AFTER
  assert_that(text, all_of(
      contains_string("Instructions"),
      contains_string("MCP servers"),
      contains_string("docker_exec")
  ))
  ```

#### Agent 22: PyHamcrest - Field-by-Field Consolidation
**Files**: Test files with multiple field checks on same object
**Effort**: 25 minutes
**Task**:
Consolidate field-by-field assertions:
```python
# BEFORE
assert info.ok is True
assert info.lines == 1
assert info.path == target

# AFTER (if all exact values)
assert info == ReadInfoResult(ok=True, lines=1, path=target)

# OR (if composed matchers needed)
assert_that(info, has_properties(
    ok=True,
    lines=greater_than(0),
    path=target
))
```

#### Agent 23: PyHamcrest - Nested Object Matchers
**Files**: Test files checking nested structures
**Effort**: 30 minutes
**Task**:
Use nested `has_properties()` pattern (from updated scan):
```python
# BEFORE (verbose)
ui_msgs = [p for p in payloads if p.get("type") == "ui_message"]
assert len(ui_msgs) > 0
assert ui_msgs[0]["message"]["mime"] == "text/markdown"

# AFTER (composable)
assert_that(payloads, has_item(
    has_properties(
        type="ui_message",
        message=has_properties(mime="text/markdown")
    )
))
```

#### Agent 24: PyHamcrest - Extract Matcher Factories
**Files**: Create new matcher helpers in `test_helpers.py` or extend existing
**Effort**: 30 minutes
**Task**:
Extract repeated patterns to matcher factories (3+ uses):
```python
# Pattern found 5+ times:
# has_properties(type="approval_pending", call_id=call_id)

# Extract to:
def has_approval_pending(call_id: str):
    return has_properties(type="approval_pending", call_id=call_id)
```

#### Agent 25: PyHamcrest - getattr() and Bare Assertions
**Files**: Test files with getattr() (4) and bare assertions (2)
**Effort**: 10 minutes
**Task**:
- Remove `getattr()` probing, use direct access or `has_properties()`
- Add error messages to bare assertions or use PyHamcrest

---

### Wave 4: Pre-commit Violations Fix (1 agent after all waves)

**Dependency**: Waves 1-3 must complete

#### Agent 26: Fix All Pre-commit Violations
**Scope**: `adgn/src/adgn/agent/`, `adgn/tests/agent/`
**Effort**: 30 minutes
**Task**:
1. Run `pre-commit run --files adgn/src/adgn/agent/**/*.py adgn/tests/agent/**/*.py`
2. Fix all violations:
   - ruff format issues
   - ruff lint issues (unused imports, line length, etc.)
   - mypy type errors (if any introduced)
3. Re-run until clean
4. Commit: "fix(agent): resolve all pre-commit violations after code quality fixes"

---

## Execution Commands

### Wave 1 (Launch 9 agents in parallel)
```bash
# Single message with 9 Task tool calls
```

### Wave 2 (Launch 6 agents in parallel, after Wave 1 completes)
```bash
# Single message with 6 Task tool calls
```

### Wave 3 (Launch 10 agents in parallel, after Wave 2 completes)
```bash
# Single message with 10 Task tool calls
```

### Wave 4 (Launch 1 agent, after Wave 3 completes)
```bash
# Single Task tool call for pre-commit fixes
```

---

## Testing Strategy

**After each wave**:
1. Collect all git commits from agents
2. Run full test suite: `pytest adgn/tests/agent -v`
3. Check for test failures (agents should run tests, but centralized check is safer)
4. If failures: Fix in Wave N+1 or dedicated fixing agent

**Final verification** (after Wave 4):
1. `pytest adgn/tests/agent -v` - all tests pass
2. `mypy adgn/src/adgn/agent` - no type errors
3. `pre-commit run --all-files` (subset: adgn/agent) - clean
4. Git log review - clean commit messages
5. Final squash/rebase if needed

---

## Success Metrics

**Wave 1 (Quick Wins):**
- ✓ 2 dead imports removed
- ✓ 146 useless comments removed
- ✓ 5 E2E helpers extracted (~100 duplication lines eliminated)

**Wave 2 (Type Safety):**
- ✓ 3 enums created (PolicyStatus, renamed RunStatus, UserApprovalDecision)
- ✓ 10 high-priority loose types tightened
- ✓ 7+ models documented with Field descriptions

**Wave 3 (PyHamcrest):**
- ✓ 110+ assertions upgraded to composable PyHamcrest matchers
- ✓ Matcher factories extracted for repeated patterns
- ✓ Nested object validation with composed matchers

**Wave 4 (Pre-commit):**
- ✓ All pre-commit hooks pass
- ✓ No mypy errors
- ✓ Clean git history

---

## Rollback Plan

If critical test failures occur:
1. Identify failing wave
2. Git revert wave commits in reverse order
3. Fix issues manually or with focused agent
4. Re-run wave with fixes

---

## Agent Prompt Template

Each agent receives:
1. **Scope**: Exact files and task from plan
2. **Context**: Reference to `adgn/SCAN_FINDINGS.md` section
3. **Examples**: From updated scan prompts (especially PyHamcrest)
4. **Requirements**:
   - Run tests after changes
   - Commit with descriptive message
   - Report files changed and test results

---

## Parallelism Rationale

**Why 9 agents in Wave 1?**
- No file overlaps
- All quick wins (5-20 min each)
- Independent changes

**Why 6 agents in Wave 2?**
- Some file overlaps (enums may touch same imports)
- Type changes may affect test files (wait for Wave 1 test cleanup)
- More complex changes (20-30 min each)

**Why 10 agents in Wave 3?**
- Many test files to migrate
- Clear task separation (isinstance, len, strings, etc.)
- Can batch by test file to avoid conflicts
- Most time-consuming wave (20-30 min each)

**Why 1 agent in Wave 4?**
- Must see all previous changes to fix violations
- Pre-commit runs holistically
- Final cleanup step
