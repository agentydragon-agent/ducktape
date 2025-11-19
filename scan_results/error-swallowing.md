# Error Swallowing Code Quality Scan Report

**Scan Date**: 2025-11-19
**Scan Type**: Error Swallowing ("Let It Crash" Principle)
**Total Files with Violations**: 46
**Total Violations**: 80

## Executive Summary

This scan identified 80 error-swallowing violations across 46 files in the codebase. The violations fall into three main categories:

- **Logging without re-raise (54 violations)**: Broad exception handlers that log but don't propagate the error
- **Pass-only handlers (20 violations)**: Silent failure patterns using `except Exception: pass`
- **Return None handlers (6 violations)**: Treating all exceptions as "not found" conditions

The most problematic pattern is **logging without re-raising**, which hides infrastructure failures while appearing to handle them. This violates the "fail fast, fail visibly" principle.

## Violation Categories

### Critical Priority: Return None Handlers (6 violations)

These are the most dangerous pattern - all exceptions are treated as normal conditions (typically "not found"):

| File | Line | Pattern |
|------|------|---------|
| `/home/user/ducktape/adgn/src/adgn/agent/server/runtime.py` | 66-68 | WebSocket accept failure → returns None instead of propagating |
| `/home/user/ducktape/k8s/helm/ember/files/rspcache_key_rotator.py` | 41-42 | Generic exception → returns None |
| `/home/user/ducktape/adgn/src/adgn/props/specimens/2025-08-29-pyright_watch_report_trajectory/filter_codex_jsonl.py` | 71-72 | Generic exception → returns None |
| `/home/user/ducktape/adgn/src/adgn/mcp/_shared/json_helpers.py` | 53-54 | JSON parsing failure → returns None |
| `/home/user/ducktape/adgn/src/adgn/mcp/policy_gateway/signals.py` | 78-79, 84-85 | Signal processing failure → returns None (2 locations) |
| `/home/user/ducktape/adgn/src/adgn/openai_utils/probe/main.py` | 460-461 | API probe failure → returns None |

**Issue**: Callers cannot distinguish between "resource doesn't exist" and "system is broken".

**Fix**: Catch only expected exceptions (e.g., `NotFoundError`), let infrastructure failures propagate.

---

### High Priority: Logging Without Re-raise (54 violations)

These handlers log the error but silently continue, hiding infrastructure failures:

#### wt/ Project (6 violations)

| File | Lines | Count |
|------|-------|-------|
| `wt/src/wt/server/gitstatusd_listener.py` | 474-483 | 1 |
| `wt/src/wt/server/github_refresh.py` | 98-100 | 1 |
| `wt/src/wt/server/worktree_service.py` | 214-215 | 1 |
| `wt/src/wt/server/wt_server.py` | 138-139, 392-394, 429-435 | 3 |
| `wt/src/wt/server/handlers/status_handler.py` | 37-38 | 1 |
| `wt/src/wt/server/rpc.py` | 157-159, 181-183 | 2 |

**Analysis**: The `wt/` (worktree) server swallows exceptions throughout its core services. These appear to be background task failures that are being logged but not escalated, potentially leaving the system in a degraded state.

**Recommendation**: Determine if these are user-facing operations (convert to specific exception handling) or infrastructure operations (remove catch, let them crash). Background task failures should trigger system alerts, not silent logging.

#### adgn/ Agent Project (17 violations)

**Critical infrastructure paths**:
- `adgn/src/adgn/agent/server/runtime.py` (2 violations, lines 105-109, 339-341): WebSocket sender loop failures being logged without re-raise
- `adgn/src/adgn/mcp/_shared/container_session.py` (4 pass-only, lines 126-128, 223-224, 254-255, 341-342): Container cleanup failures silently ignored
- `adgn/src/adgn/mcp/exec/seatbelt.py` (5 violations, lines 154-156, 171-172, 175-176, 203-205, 212-214): Policy/approval system logging without re-raise

**User-facing paths**:
- `adgn/src/adgn/mcp/notifications/buffer.py` (1 violation, line 119-120): Notification buffering failure
- `adgn/src/adgn/mcp/matrix/server.py` (6 violations): Matrix client failures scattered across connection/session management

#### HTTP Logging (8 violations)

`adgn/src/adgn/openai_utils/http_logging.py` has 8 logging-without-reraise violations in HTTP interceptor code. These appear to be middleware hooks that should fail fast rather than silently continue.

#### MCP/Ember (13 violations)

- `ember/src/ember/matrix_client.py` (6 violations): Matrix client operations
- `ember/src/ember/runtime/python_session.py` (1 violation): Python session management
- `ember/src/ember/tools/read_image.py` (1 violation): Image reading
- `llm/mcp/habitify/` (3 violations): Habitify MCP server operations
- `llm/html/llm_html/server.py` (2 violations): HTML server operations

#### Claude Hooks (2 violations)

- `claude/claude_hooks/claude_hooks/base.py` (1 violation, line 125-130): Hook base class
- `claude/claude_hooks/claude_hooks/precommit_autofix.py` (1 violation, line 178-198): Pre-commit hook autofix

#### Other (4 violations)

- `mcp_starter/manual_test_sdk.py` (1): Test utility
- `llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/cli.py` (1): Linter CLI
- `adgn/src/adgn/mcp/sandboxed_jupyter/jupyter_sandbox_compose.py` (2): Jupyter sandbox
- `gatelet/gatelet/server/endpoints/` (2): Gateway endpoints

---

### Medium Priority: Pass-Only Handlers (20 violations)

These are silent failures with no logging, making them completely invisible:

#### Test Fixtures (3 violations)

These are intentional bad examples used for testing the detector:
- `adgn/tests/detectors/fixtures/bad/swallow_errors.py` (line 3-4)
- `adgn/tests/detectors/fixtures/bad/broad_except_order.py` (line 3-4)
- `adgn/tests/detectors/fixtures/ok/compliant_broad_except_order.py` (line 5-6) - Questionable

#### Test Code (4 violations)

These are in test cleanup that may be intentional but lack documentation:
- `adgn/tests/agent/e2e/test_ui.py` (line 81-82)
- `adgn/tests/agent/e2e/test_mcp_errors.py` (line 304-306)
- `adgn/tests/agent/e2e/test_mcp_edge_cases.py` (line 178-179, 259-260)
- `adgn/tests/agent/ui/test_ui_agent_integration.py` (line 71-73)
- `adgn/tests/llm/test_specimens_valid_strict.py` (line 39-40)

**Analysis**: Most test pass-only handlers appear to be cleanup in `finally` blocks or teardown phases, which may be acceptable for best-effort cleanup.

#### Production Code (13 violations)

**Critical infrastructure**:
- `adgn/src/adgn/mcp/_shared/container_session.py` (4 violations, lines 126-128, 223-224, 254-255, 341-342): Container lifecycle failures being silently ignored
- `llm/ducktape_llm_common/ducktape_llm_common/hook_session_state.py` (1 violation, line 83-85): Session state cleanup

**Tool code**:
- `adgn/src/adgn/props/specimens/2025-08-29-pyright_watch_report/code/pyright_watch_report.py` (line 50-51): Specimen code example

---

## Risk Assessment by Component

### 🔴 Critical (Immediate Fix Needed)

1. **adgn/src/adgn/agent/server/runtime.py** (3 violations)
   - WebSocket connection failures returning None or being silently logged
   - These are infrastructure failures that should crash the connection handler
   - Impact: Broken connections appearing successful, client-server desync

2. **adgn/src/adgn/mcp/_shared/container_session.py** (4 violations)
   - Container cleanup failures being silently ignored
   - Impact: Containers may leak, resources not released, next operations may fail

3. **adgn/src/adgn/mcp/exec/seatbelt.py** (5 violations)
   - Approval policy system logging failures without re-raising
   - Impact: Policy violations may silently proceed, security boundary compromised

### 🟠 High (Important, Should Fix)

1. **adgn/src/adgn/openai_utils/http_logging.py** (8 violations)
   - HTTP interceptor failures being silently absorbed
   - Impact: API communication logging broken, observability lost

2. **ember/src/ember/** (13 violations across matrix client and tools)
   - Matrix communication and Python execution failures being logged without re-raise
   - Impact: Degraded chat/execution without user notification

3. **wt/src/wt/server/** (6 violations)
   - Worktree service failures scattered across multiple modules
   - Impact: Git operations appear to succeed but may be in inconsistent state

4. **Return None handlers** (6 violations)
   - All infrastructure failures treated as "not found"
   - Impact: Impossible to distinguish actual missing resources from broken systems

### 🟡 Medium (Should Review)

1. **Test code** (9 violations)
   - Mostly cleanup/teardown patterns that may be acceptable
   - Should add comments documenting why exception is intentionally swallowed

2. **Pass-only in socket/connection cleanup** (3 violations)
   - May be acceptable for best-effort cleanup (connection already closed)
   - Should use `contextlib.suppress()` with comments explaining the reason

3. **Linter/tool code** (4 violations)
   - Lower impact than core infrastructure
   - Still should follow "let it crash" principle for clarity

---

## Violation Patterns & Fixes

### Pattern 1: Connection/WebSocket Cleanup

**Current (problematic)**:
```python
except Exception:
    # If connection already closed, we don't care
    return None
```

**Issue**: Can't distinguish "connection closed" from "serious error".

**Better approach**:
```python
# Remove the try-except entirely, or:
try:
    await ws.send(data)
except ConnectionClosedError:
    return None  # Expected - connection is gone
# Let other exceptions propagate
```

### Pattern 2: Background Task Failures

**Current (problematic)**:
```python
try:
    await critical_operation()
except Exception as e:
    logger.error(f"Operation failed: {e}")
    # Silently continues...
```

**Issue**: Infrastructure failure is logged but system continues in broken state.

**Fix**: Let the exception propagate to the task supervisor, which will handle restart/escalation:
```python
# Remove try-except entirely
await critical_operation()
# System crashes if operation fails
```

### Pattern 3: Container/Resource Cleanup

**Current (problematic)**:
```python
except Exception:
    pass  # Best effort
```

**Issue**: Resources may leak, next operation fails unexpectedly.

**Better**:
```python
except Exception:
    # Log clearly what failed
    logger.error("Failed to clean up container", exc_info=True)
    raise  # Let caller decide if recoverable
```

### Pattern 4: Validation/User Input

**Current (good)**:
```python
try:
    config = parse_user_input(data)
except ValidationError as e:
    return {"error": str(e)}  # Specific exception only
```

**Why it's OK**: User error is expected and handled gracefully.

---

## Detailed Violation List by File

### adgn/src/adgn/agent/server/runtime.py

**Lines 66-68** (WebSocket accept)
- Type: `return None`
- Severity: Critical
- Description: WebSocket accept failure returns None instead of propagating
- Fix: Let ConnectionError propagate, handle at route layer

**Lines 105-109** (Sender loop)
- Type: `log_no_reraise`
- Severity: Critical
- Description: WebSocket send failure logged but sender loop continues
- Fix: Re-raise after logging to stop broken sender loop

**Lines 339-341**
- Type: `log_no_reraise`
- Severity: High
- Description: Unknown operation failure being logged without re-raise
- Action: Examine context and classify appropriately

### wt/src/wt/server/

Multiple files with logging-without-reraise patterns in background tasks:
- `gitstatusd_listener.py:474` - Git status listener failure
- `github_refresh.py:98` - GitHub API refresh failure
- `worktree_service.py:214` - Core service operation failure
- `wt_server.py:138,392,429` - Multiple RPC/service failures
- `handlers/status_handler.py:37` - Status endpoint failure
- `rpc.py:157,181` - RPC handler failures

**Pattern**: Background tasks logging and continuing despite failures.

**Recommendation**: Each should be analyzed to determine if:
1. User-facing (return error to client)
2. Infrastructure (remove catch, crash task)
3. Transient (add retry logic with exponential backoff)

### adgn/src/adgn/mcp/_shared/container_session.py

**Lines 126-128, 223-224, 254-255, 341-342** (All `pass_only`)
- Severity: High
- Description: Container lifecycle operations silently failing
- Impact: Resource leaks, stale containers, unexpected state
- Fix: Log the error and re-raise, let container system detect and handle failure

**Recommendation**: Add specific exception handling and re-raise:
```python
except TimeoutError:
    logger.error("Container operation timeout", exc_info=True)
    raise
except Exception as e:
    logger.error("Container operation failed", exc_info=True)
    raise  # Don't swallow - let supervisor restart container
```

### adgn/src/adgn/mcp/exec/seatbelt.py

**Lines 154-156, 171-172, 175-176, 203-205, 212-214** (All `log_no_reraise`)
- Severity: Critical
- Description: Approval policy/seatbelt failures being logged without re-raise
- Impact: Security boundary may be bypassed, execution allowed when policy denies
- Fix: Re-raise all policy failures to maintain security invariant

### adgn/src/adgn/openai_utils/http_logging.py

**Lines 51-53, 71-73, 78-84, 82-84, 103-105, 123-125, 131-137, 135-137**
- Severity: High
- Description: HTTP interceptor failures (8 violations)
- Impact: API observability compromised, debugging impossible
- Pattern: Logging failures in HTTP middleware without propagating
- Fix: These should either re-raise or use structured error responses

---

## Remediation Roadmap

### Phase 1: Critical (Week 1)

1. **adgn/src/adgn/agent/server/runtime.py**
   - Fix WebSocket handler failures (lines 66-68, 105-109)
   - Ensure connection errors propagate to client
   - Update return type annotations

2. **adgn/src/adgn/mcp/exec/seatbelt.py**
   - Re-raise all approval policy failures
   - Verify security boundary cannot be bypassed by missing errors

3. **adgn/src/adgn/mcp/_shared/container_session.py**
   - Replace pass-only with proper error handling
   - Add logging before re-raise

### Phase 2: High (Week 2-3)

1. **wt/src/wt/server/** (6 violations)
   - Audit each background task failure
   - Classify and fix according to error type
   - Add retry logic where appropriate

2. **adgn/src/adgn/openai_utils/http_logging.py**
   - Review HTTP interceptor design
   - Fix 8 violations, ensure observability

3. **Return None handlers** (6 violations)
   - Update all "except Exception: return None" to catch specific exceptions
   - Update caller code to handle propagating exceptions
   - Update type annotations

### Phase 3: Medium (Week 3-4)

1. **Test code** (9 violations)
   - Add comments explaining why exceptions are swallowed
   - Convert to `contextlib.suppress()` where appropriate
   - Document any best-effort cleanup patterns

2. **Other infrastructure** (ember/, llm/, etc.)
   - Apply same classification and fixes as Phase 1-2

---

## Success Criteria

After remediation, this scan should show:

1. ✅ **Zero critical violations**
   - No "return None on Exception" patterns
   - No infrastructure operation silent failures
   - Security boundaries always enforced

2. ✅ **Documented best-effort cleanups**
   - All `except: pass` explained with comments
   - Use of `contextlib.suppress()` for optional operations
   - Clear documentation of why error is safe to ignore

3. ✅ **Proper error propagation**
   - Infrastructure failures crash immediately
   - User errors handled with specific exception types
   - Clear error messages at crash point

4. ✅ **Type annotations updated**
   - Remove unnecessary `| None` return types
   - Add exception documentation to docstrings
   - Type checker passes with `--strict`

---

## Testing Strategy

After fixes are applied:

```bash
# Run the detector to verify fixes
adgn-properties2 run --specimen error-swallowing --structured true

# Type check with strict mode
mypy --strict adgn/src/adgn/

# Run full test suite - errors should surface clearly
pytest adgn/tests/ -v

# Verify crashes are visible
# - Infrastructure failures should show stack traces
# - User errors should be caught at API boundary
# - System should not silently degrade
```

---

## References

- Scan Definition: `prompts/scans/error-swallowing.md`
- Detector: `adgn/src/adgn/props/detectors/det_swallow_errors.py`
- Related AGENTS.md: "Do not swallow exceptions" section in `adgn/AGENTS.md`
- FastMCP Best Practices: `adgn/instructions/fastmcp_exceptions.md`

---

## Report Metadata

- **Generated**: 2025-11-19
- **Scan Method**: AST analysis of all Python files
- **Total Files Scanned**: 943
- **Files with Violations**: 46 (4.9%)
- **Total Violations**: 80
- **Distribution**:
  - Log-without-reraise: 54 (67.5%) - **Most problematic**
  - Pass-only: 20 (25.0%)
  - Return None: 6 (7.5%) - **Most dangerous**
