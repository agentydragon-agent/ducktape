# Code Quality Scan Report: Suspicious Default Values

**Scan Date**: 2025-11-19
**Repository**: ducktape
**Scan Type**: Suspicious defaults (defensive `or` operators masking type safety issues)
**Total Violations Found**: 236
**Files Affected**: 119
**Target Precision**: Medium (~60%) with High Recall (~90%)

## Executive Summary

This scan identified **236 instances** of suspicious default patterns across **119 files** in the ducktape repository. These patterns indicate potential type safety issues where `or` operators are used defensively with literal defaults (`{}`, `""`, `[]`, `()`), suggesting a mismatch between type annotations and runtime behavior.

### Key Findings by Pattern

| Pattern | Count | Type |
|---------|-------|------|
| `or {}` | ~75 | Dictionary defaults (most critical) |
| `or ""` | ~95 | String defaults (high frequency) |
| `or []` | ~45 | List defaults (moderate frequency) |
| `or ''` | ~15 | Single-quote string defaults |
| `or ()` | ~6 | Tuple defaults (rare) |

### High-Impact Areas

1. **Matrix Integration** (`ember/`, `adgn/`): 14 violations in matrix client code
2. **CLI and Configuration** (`wt/cli.py`, `adgn/props/cli_app/`): 16+ violations
3. **MCP and Agent Infrastructure** (`adgn/mcp/`, `adgn/agent/`): 25+ violations
4. **Test Utilities** (`adgn/tests/`, `wt/tests/`): 20+ violations

---

## Detailed Findings by File (Top 20)

### 1. `/home/user/ducktape/wt/src/wt/cli.py` — 9 violations

**Pattern**: Multiple `ctx.obj or {}` defensive checks

```python
Line 115:  ctx.obj = ctx.obj or {}
Line 291:  verbose = bool((ctx.obj or {}).get("verbose", False))
Line 310:  verbose = bool((ctx.obj or {}).get("verbose", False))
Line 318:  verbose = bool((ctx.obj or {}).get("verbose", False))
Line 329:  verbose = bool((ctx.obj or {}).get("verbose", False))
Line 341:  verbose = bool((ctx.obj or {}).get("verbose", False))
Line 351:  verbose = bool((ctx.obj or {}).get("verbose", False))
Line 359:  verbose = bool((ctx.obj or {}).get("verbose", False))
Line 379:  verbose = bool((ctx.obj or {}).get("verbose", False))
```

**Analysis**:
- Click context object is typed as `dict | None` in the function signature
- Multiple defensive checks suggest `ctx.obj` is typed as optional but should be required
- **Recommendation**: Either make `ctx.obj` non-optional initially or handle None explicitly once at the start of each command, not on every access

---

### 2. `/home/user/ducktape/ember/src/ember/matrix_client.py` — 7 violations

**Lines**: 202, 217, 218, 219, 241, 244, 336

```python
Line 202:  return {RoomID(room_id) for room_id in (response.rooms or [])}
Line 217:  len(response.rooms.join or {}),
Line 218:  len(response.rooms.invite or {}),
Line 219:  len(response.rooms.leave or {}),
Line 241:  joined = response.rooms.join or {}
Line 244:  timeline = room.timeline.events or []
Line 336:  events = invite.invite_state or []
```

**Analysis**:
- Multiple defensive checks on Matrix API response objects
- If `response.rooms` can be None, the type should reflect this
- If it's guaranteed non-None, the defensive checks are unnecessary
- **Recommendation**: Check the upstream Matrix library types and either:
  1. Update type annotations to reflect actual nullability
  2. Remove defensive `or` operators if types are correct

---

### 3. `/home/user/ducktape/adgn/src/adgn/agent/matrix_bot.py` — 7 violations

**Lines**: 111, 112, 119, 120, 121, 122, 69

```python
Line 111:  ex = TypeAdapter(BaseExecResult).validate_python(res.structuredContent or {})
Line 112:  stdout_stream = ex.stdout or ""
Line 119:  return since or "", False
Line 120:  next_since = data.get("next_batch") or (since or "")
Line 121:  rooms = (data.get("rooms") or {}).get("join") or {}
Line 122:  events = (rooms.get(room) or {}).get("timeline", {}).get("events", [])
Line 69:   effective_system = (system or "").strip() or (...)
```

**Analysis**:
- Nested defensive defaults suggest type uncertainty
- Double `or` patterns (line 120, 121) indicate cascading type coercion
- **Severity**: MEDIUM - pattern obscures actual type contract
- **Recommendation**: Flatten the logic; make type contract explicit

---

### 4. `/home/user/ducktape/adgn/src/adgn/props/cli_app/main.py` — 7 violations

**Analysis**: CLI argument parsing with defensive defaults

**Recommendation**: Verify that argument parsers properly enforce required vs optional parameters

---

### 5. `/home/user/ducktape/adgn/src/adgn/mcp/notifying_fastmcp.py` — 6 violations

**Analysis**: MCP server setup code using defensive defaults

**Recommendation**: Document which MCP fields are truly optional vs which should be required

---

### 6. `/home/user/ducktape/adgn/src/adgn/git_commit_ai/cli.py` — 6 violations

**Analysis**: CLI tool with string formatting defaults

**Recommendation**: Use explicit None checks or provide proper type annotations

---

## Pattern Analysis

### Pattern: `or {}` (Dictionary Defaults)

**Total Count**: ~75
**Severity**: MEDIUM-HIGH
**Typical Occurrences**:
- MCP server responses
- API response parsing
- Configuration merging

**Common Causes**:
1. Upstream library returns `None` despite type saying `dict[str, Any]`
2. Defensive programming to avoid `AttributeError` on None
3. Legacy code where optional dicts were normalized at runtime

**Example - Problematic**:
```python
schema = tool.inputSchema or {}  # Type says non-None but code doesn't trust it
props = schema.get("properties", {})
```

**Example - Better**:
```python
# Either trust the type:
props = tool.inputSchema.get("properties", {})

# Or handle None explicitly:
if tool.inputSchema is not None:
    props = tool.inputSchema.get("properties", {})
else:
    props = {}
```

---

### Pattern: `or ""` (String Defaults)

**Total Count**: ~95
**Severity**: MEDIUM
**Typical Occurrences**:
- String formatting and concatenation
- Optional text fields
- Logging/display purposes

**Common Causes**:
1. Optional string fields being concatenated
2. Defensive guards against None in string operations
3. Legitimate cases where None == empty string semantically

**Example - Valid Case**:
```python
# OK: None and "" are semantically equivalent here
description = tool.description or ""  # Display purposes
```

**Example - Suspicious Case**:
```python
# BAD: Type mismatch
def format_error(message: str | None) -> str:
    return f"Error: {message or ''}"
# Better:
def format_error(message: str | None) -> str:
    if message is None:
        return "Error: (no message)"
    return f"Error: {message}"
```

---

### Pattern: `or []` (List Defaults)

**Total Count**: ~45
**Severity**: LOW-MEDIUM
**Typical Occurrences**:
- Iteration over optional sequences
- Collection processing
- API response lists

**Example - Suspicious**:
```python
for item in collection or []:  # Type says non-None?
    process(item)
```

**Better**:
```python
if collection is not None:
    for item in collection:
        process(item)
```

---

## Categorized Recommendations

### Critical Issues (Fix Immediately)

1. **Type Annotation Mismatches in MCP Code**
   - Files: `adgn/mcp/*.py`, `adgn/agent/matrix_bot.py`
   - Action: Review upstream type definitions and either:
     - Update local types to match reality
     - Fix defensive `or` operators once type is correct

2. **Nested Defensive Defaults**
   - Pattern: `(x or {}).get(...) or {...}`
   - Action: Flatten and use explicit None handling

3. **String Concatenation with `or ""`**
   - In: `adgn/src/adgn/agent/matrix_bot.py:69`
   - Action: Use explicit conditional instead

### Medium Priority (Refactor)

1. **Click Context Management** (`wt/src/wt/cli.py`)
   - Initialize context once at entry point
   - Remove repeated defensive checks throughout

2. **Matrix Client Defensive Checks**
   - Verify upstream matrix-client types
   - Use TypeAdapter validation at boundary
   - Remove interior defensive `or` operators

3. **Configuration and CLI Parsing**
   - Files: `adgn/src/adgn/props/cli_app/main.py`, `adgn/src/adgn/git_commit_ai/cli.py`
   - Action: Use proper default parameter handling in argument parsers

### Low Priority (Document)

1. **Legitimate Falsy-to-Default Cases**
   - Example: `count or 10` (falsy 0 means use default)
   - Action: Add clarifying comments

2. **Backward Compatibility Shims**
   - Example: Legacy API accepting None for compatibility
   - Action: Add TODO with deprecation timeline

---

## High-Frequency File List

| File | Violations | Primary Pattern | Priority |
|------|------------|-----------------|----------|
| `wt/src/wt/cli.py` | 9 | `or {}` | HIGH |
| `ember/src/ember/matrix_client.py` | 7 | `or []`, `or {}` | HIGH |
| `adgn/src/adgn/agent/matrix_bot.py` | 7 | mixed | HIGH |
| `adgn/src/adgn/props/cli_app/main.py` | 7 | `or ""` | MEDIUM |
| `adgn/src/adgn/mcp/notifying_fastmcp.py` | 6 | `or {}` | MEDIUM |
| `adgn/src/adgn/git_commit_ai/cli.py` | 6 | `or ""` | MEDIUM |
| `adgn/tests/agent/test_mcp_notifications_flow.py` | 6 | `or []` | LOW |
| `adgn/src/adgn/props/cluster_unknowns.py` | 6 | `or ""` | MEDIUM |
| `adgn/src/adgn/mcp/git_ro/server.py` | 5 | mixed | MEDIUM |
| `llm/ducktape_llm_common/claude_linter_v2/hooks/handler.py` | 5 | `or ""` | MEDIUM |

---

## Remediation Steps

### For Each File

1. **Run mypy with strict mode**:
   ```bash
   mypy --strict <file.py>
   ```
   This will reveal type mismatches that the defensive `or` operators are masking.

2. **Analyze each violation**:
   - What is the declared type?
   - Can it actually be None at runtime?
   - Should it be `T | None` or just `T`?

3. **Apply appropriate fix**:
   - Remove unnecessary `or` if type is correctly non-None
   - Add explicit None checks if type should be nullable
   - Update type annotation if actual runtime allows None

4. **Verify with tests**:
   ```bash
   pytest --tb=short <test_file>
   mypy --config-file pyproject.toml <file.py>
   ```

### Automation Opportunities

Run this sweep across high-impact files:

```bash
# Step 1: Identify files needing attention
rg --type py "or \{\}|or \"\"|or ''" --files | sort | uniq > /tmp/files_to_review.txt

# Step 2: Run mypy on each
for file in $(cat /tmp/files_to_review.txt); do
    echo "=== $file ==="
    mypy --strict "$file" 2>&1 | head -20
done

# Step 3: Track fixes in git
git add <fixed_files>
git commit -m "fix: remove suspicious defaults masking type issues"
```

---

## False Positives (Acceptable)

The following patterns are acceptable and don't require fixes:

1. **Boolean Coercion with Counts**:
   ```python
   count = config.get_count() or 10  # 0 means "use default"
   ```

2. **Empty String Equivalence (Documented)**:
   ```python
   # OK if None and "" are semantically identical:
   description = field.description or ""  # For display purposes
   ```

3. **Backward Compatibility Marked with TODO**:
   ```python
   # TODO(2025-12): Remove when all callers updated
   def legacy_api(data: dict[str, Any] | None = None) -> None:
       data = data or {}  # Compatibility: treat None as empty
   ```

---

## Scan Methodology

### Detection Strategy
- **Tool**: ripgrep (`rg`)
- **Pattern**: `or \{\}|or \"\"|or ''|or \[\]|or \(\)`
- **Scope**: All Python files in `/home/user/ducktape`
- **Recall Target**: ~90% (high false positive rate acceptable)
- **Precision**: ~60% (requires manual review)

### Limitations
- Pattern is syntactic; doesn't verify actual type safety
- Legitimate uses (boolean coercion, intentional equivalence) included in results
- Requires manual analysis per occurrence

---

## Next Steps

1. **Triage**: Team reviews high-priority files (wt/cli.py, matrix_*.py)
2. **Type Audit**: Run mypy strict on each file to reveal actual issues
3. **Fix**: Apply remediation strategy per finding
4. **Verify**: Run tests and type checking after each fix
5. **Document**: Add comments for legitimate uses with explanation

---

## Related Documentation

- See `prompts/scans/suspicious-defaults.md` for detailed scan strategy
- Type safety best practices in project AGENTS.md
- MCP type conventions in `adgn/instructions/fastmcp_pydantic.md`
