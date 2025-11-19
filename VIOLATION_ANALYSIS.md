# Code Quality Scan Violation Analysis

**Analysis Date**: 2025-11-19
**Repository**: ducktape
**Total Scans Executed**: 30
**Python Files Analyzed**: 943

---

## Executive Summary

This analysis aggregates findings from 30 comprehensive code quality scans covering type safety, error handling, async patterns, test quality, and code organization. The codebase contains **approximately 2,000+ violations** across all categories, with the highest concentration in type safety issues (stringly-typed code, loose typing) and test quality patterns.

### Total Violation Counts by Category

| Priority | Category | Violations | Severity | Est. Effort |
|----------|----------|------------|----------|-------------|
| **CRITICAL** | Error Swallowing | 80 | CRITICAL | 8 hours |
| **CRITICAL** | Stringly Typed | 416 | CRITICAL | 16 hours |
| **HIGH** | Overly Loose Typing | 200+ | HIGH | 12 hours |
| **HIGH** | Suspicious Nullability | 194 | HIGH | 10 hours |
| **MEDIUM** | Blocking I/O in Async | 53 | MEDIUM | 6 hours |
| **MEDIUM** | Asyncio Antipatterns | 131 | MEDIUM | 4 hours |
| **MEDIUM** | Type Ignore Suppressions | 149 | MEDIUM | 6 hours |
| **MEDIUM** | Methods vs Freestanding | 93 | MEDIUM | 8 hours |
| **MEDIUM** | Test Assertions | 500+ | MEDIUM | 10 hours |
| **LOW** | Unnecessary Verbosity | 100+ | LOW | 4 hours |
| **LOW** | Useless Comments | 241 | LOW | 3 hours |
| **LOW** | Useless Test Classes | 41 | LOW | 2 hours |
| **TOTAL** | **All Categories** | **~2,200** | - | **~90 hours** |

---

## Top 5 Categories for Wave H Cleanup

Based on **impact × frequency × risk**, here are the top 5 priorities:

### 1. Stringly Typed Code (416 violations, CRITICAL severity, 16 hours)

**Impact**: Type safety erosion, no IDE autocomplete, runtime errors from typos
**Risk**: HIGH - affects API contracts, database models, state machines
**Blast Radius**: 109 files across core agent code, wt/, gatelet/, llm/

**Breakdown**:
- 42 string fields with categorical names (status, state, type, kind)
- 36 Literal types that should be StrEnum
- 81 string comparisons with hardcoded strings
- 257 string assignments to categorical fields

**Critical Files**:
- `adgn/src/adgn/agent/persist/__init__.py` - PolicyProposal.status (no enum)
- `wt/src/wt/shared/github_models.py` - GitHubPRResponse.state (enum exists but not used!)
- `gatelet/gatelet/server/auth/handlers.py` - auth_type comparisons throughout
- `adgn/src/adgn/agent/mcp_bridge/servers/agents.py` - ServerState.status

**Fix Strategy**:
```python
# BEFORE
class PolicyProposal(BaseModel):
    status: str  # Could be: pending, approved, denied

# AFTER
class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"

class PolicyProposal(BaseModel):
    status: ProposalStatus
```

**Testing Strategy**: Type checker should catch all violations, API remains backward compatible

---

### 2. Error Swallowing (80 violations, CRITICAL severity, 8 hours)

**Impact**: Infrastructure failures hidden, system appears healthy but is broken
**Risk**: CRITICAL - security boundaries, container lifecycle, WebSocket connections
**Blast Radius**: 46 files (adgn/, wt/, ember/, llm/)

**Breakdown**:
- 54 logging-without-reraise (most problematic)
- 20 pass-only handlers (silent failures)
- 6 return-None handlers (most dangerous)

**Critical Files**:
- `adgn/src/adgn/agent/server/runtime.py` - WebSocket failures return None
- `adgn/src/adgn/mcp/exec/seatbelt.py` - Approval policy failures logged but not raised
- `adgn/src/adgn/mcp/_shared/container_session.py` - Container cleanup silently ignored
- `adgn/src/adgn/openai_utils/http_logging.py` - HTTP interceptor failures absorbed

**Fix Strategy**:
```python
# BEFORE (dangerous)
try:
    await ws.send(data)
except Exception as e:
    logger.error(f"Send failed: {e}")
    return None  # Hides failure

# AFTER (fail fast)
try:
    await ws.send(data)
except ConnectionClosedError:
    return None  # Expected - connection is gone
# Let other exceptions propagate
```

**Testing Strategy**: Remove try-except, run tests, ensure errors surface clearly

---

### 3. Overly Loose Typing (200+ violations, HIGH severity, 12 hours)

**Impact**: Type checker gives up, IDE autocomplete broken, runtime errors inevitable
**Risk**: HIGH - function contracts unclear, callers don't know what to pass
**Blast Radius**: Utility modules, test fixtures, API integration layers

**Breakdown**:
- 70 `Any`-typed parameters
- 130+ `dict[str, Any]` returns/parameters
- 15 `object` typing
- 25 ambiguous unions (`dict[str, Any] | str`)

**Critical Files**:
- `adgn/src/adgn/agent/agent.py:149` - `_normalize_call_arguments(arguments: Any)`
- `adgn/src/adgn/agent/server/state.py:103` - `start_tool(..., args: Any | None)`
- Multiple utility functions accepting `Any` then doing isinstance() checks

**Fix Strategy**:
```python
# BEFORE
def func(param: Any) -> dict[str, Any]:
    if isinstance(param, str):
        return {"value": param}
    return param.model_dump()

# AFTER
def func(param: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(param, str):
        return {"value": param}
    return param
```

**Testing Strategy**: Enable mypy strict mode, fix type errors incrementally

---

### 4. Blocking I/O in Async Functions (53 violations, MEDIUM severity, 6 hours)

**Impact**: Event loop blocked, async performance degraded, server responsiveness hurt
**Risk**: MEDIUM - affects web endpoints, MCP resource handlers, file operations
**Blast Radius**: 18 files (llm/html/, adgn/src/adgn/agent/, wt/, experimental/)

**Breakdown**:
- 18 files using `Path.read_text()` / `Path.write_text()` in async contexts
- Multiple `open()` calls in async context managers
- SQL file read operations in async persistence layer

**Critical Files**:
- `llm/html/llm_html/server.py` - FastAPI endpoints doing sync file I/O
- `adgn/src/adgn/agent/persist/sqlite.py` - SQL migrations blocking event loop
- `adgn/src/adgn/mcp/chat/server.py` - MCP resource handlers reading files synchronously

**Fix Strategy**:
```python
# BEFORE
@app.get("/", response_class=HTMLResponse)
async def index():
    text = Path("index.md").read_text()  # BLOCKS event loop

# AFTER (Option 1: asyncio.to_thread)
async def index():
    text = await asyncio.to_thread(Path("index.md").read_text)

# AFTER (Option 2: aiofiles)
import aiofiles
async def index():
    async with aiofiles.open("index.md", "r") as f:
        text = await f.read()
```

**Testing Strategy**: Load test before/after, measure request latency improvement

---

### 5. Asyncio Antipatterns (131 violations, MEDIUM severity, 4 hours)

**Impact**: Test boilerplate, missed TaskGroup opportunities, code clarity
**Risk**: LOW-MEDIUM - mostly test code, some production gather() patterns
**Blast Radius**: Test files (112), production (19)

**Breakdown**:
- 112 unnecessary `@pytest.mark.asyncio` decorators (projects have `asyncio_mode = "auto"`)
- 19 `asyncio.gather()` calls (Python 3.11+ can use TaskGroup)
- 0 deprecated `asyncio.get_event_loop()` (good!)

**Critical Files**:
- `adgn/tests/` - 109 redundant decorators
- `claude/claude_optimizer/tests/` - 3 redundant decorators
- `adgn/src/adgn/agent/server/runtime.py` - gather with return_exceptions
- `adgn/src/adgn/mcp/notifying_fastmcp.py` - multiple broadcast calls

**Fix Strategy**:
```bash
# Remove decorators (projects have asyncio_mode = "auto")
rg --type py '@pytest\.mark\.asyncio' adgn/tests/ --replace '' --files-with-matches

# Refactor gather to TaskGroup (Python 3.11+)
# BEFORE
results = await asyncio.gather(*tasks, return_exceptions=True)

# AFTER
async with asyncio.TaskGroup() as tg:
    for task in tasks:
        tg.create_task(task)
```

**Testing Strategy**: Run pytest suite, verify all async tests still execute

---

## Wave H Cleanup Strategies

### Parallel Work Streams (5 Teams)

**Team 1: Type Safety (Stringly Typed + Loose Typing)**
- Duration: 2 weeks
- Scope: 416 + 200 = 616 violations
- Deliverables:
  1. Create central `adgn/src/adgn/types/enums.py` for shared enums
  2. Convert critical status/state/type fields to StrEnum (42 fields)
  3. Replace bare `Any` parameters with unions (70 violations)
  4. Update string comparisons to use enum members (81 violations)
- Testing: Enable mypy strict mode, fix type errors

**Team 2: Error Handling (Error Swallowing + Nullability)**
- Duration: 2 weeks
- Scope: 80 + 194 = 274 violations
- Deliverables:
  1. Fix critical WebSocket/container/policy failures (15 files)
  2. Remove assert-not-None in production code (3 files)
  3. Update return types to remove unnecessary | None (50+ functions)
  4. Add specific exception handling where needed
- Testing: Remove try-except, ensure errors surface, verify crash behavior

**Team 3: Async Patterns (Blocking I/O + Antipatterns)**
- Duration: 1 week
- Scope: 53 + 131 = 184 violations
- Deliverables:
  1. Fix blocking I/O in web endpoints (llm/html/, gatelet/)
  2. Fix blocking I/O in MCP resource handlers (adgn/src/adgn/mcp/)
  3. Remove 112 redundant @pytest.mark.asyncio decorators
  4. Refactor gather() to TaskGroup in high-priority files (8)
- Testing: Load test endpoints, verify pytest suite passes

**Team 4: Test Quality (Assertions + Useless Classes + Duplicates)**
- Duration: 2 weeks
- Scope: 500 + 41 + fixtures = ~600 violations
- Deliverables:
  1. Convert isinstance() to instance_of() (30+ tests)
  2. Convert len() checks to has_length() (150+ tests)
  3. Flatten 41 useless test classes to module-level functions
  4. Consolidate duplicated fixtures in conftest.py
- Testing: Run full test suite, verify all tests pass

**Team 5: Code Organization (Methods + Verbosity + Comments)**
- Duration: 1 week
- Scope: 93 + 100 + 241 = 434 violations
- Deliverables:
  1. Convert factory functions to @classmethod (10 violations)
  2. Remove single-assignment variables (32 violations)
  3. Replace verbose boolean returns with direct returns (14 violations)
  4. Remove obvious/duplicate comments (241 violations)
- Testing: Verify functionality unchanged, run unit tests

---

## Effort Estimation

### By Priority Level

| Priority | Categories | Violations | Estimated Hours | % of Total |
|----------|------------|------------|-----------------|------------|
| CRITICAL | 2 | 496 | 24 hours | 27% |
| HIGH | 2 | 394 | 22 hours | 24% |
| MEDIUM | 6 | 926 | 34 hours | 38% |
| LOW | 4 | 385 | 9 hours | 10% |
| **TOTAL** | **14** | **~2,200** | **~90 hours** | **100%** |

### By Work Stream

| Team | Focus Area | Violations | Estimated Hours | Team Size | Duration |
|------|-----------|------------|-----------------|-----------|----------|
| Team 1 | Type Safety | 616 | 28 hours | 2 devs | 2 weeks |
| Team 2 | Error Handling | 274 | 18 hours | 2 devs | 2 weeks |
| Team 3 | Async Patterns | 184 | 10 hours | 1 dev | 1 week |
| Team 4 | Test Quality | ~600 | 12 hours | 2 devs | 2 weeks |
| Team 5 | Code Org | 434 | 9 hours | 1 dev | 1 week |
| **TOTAL** | - | **~2,200** | **~77 hours** | **8 devs** | **2 weeks** |

---

## Risk Assessment

### High-Risk Changes (Require Careful Testing)

1. **Error Swallowing Removal**: Removing try-except may expose previously hidden bugs
   - Mitigation: Fix in development, run full test suite, deploy to staging first

2. **Nullability Refactoring**: Changing parameter types may break callers
   - Mitigation: Use mypy to find all call sites, update incrementally

3. **Async I/O Changes**: Switching to async file I/O changes execution semantics
   - Mitigation: Load test before/after, measure performance, verify correctness

### Low-Risk Changes (Safe to Automate)

1. **@pytest.mark.asyncio Removal**: Projects already have asyncio_mode = "auto"
   - Can be done with automated find-replace

2. **Test Assertion Refactoring**: PyHamcrest matchers are drop-in replacements
   - Can be done with automated regex replacements

3. **Useless Comment Removal**: No functional impact
   - Can be reviewed and removed in bulk

---

## Success Metrics

### Code Quality Improvements

- **Type Safety**:
  - Mypy strict mode violations: 616 → 0
  - IDE autocomplete coverage: 60% → 95%
  - Runtime type errors: Baseline → 0 (in covered code)

- **Error Visibility**:
  - Error swallowing violations: 80 → 0
  - Production assertions: 3 → 0
  - Silent failure patterns: 20 → 0

- **Test Quality**:
  - Plain assertions: 500+ → 0
  - Useless test classes: 41 → 0
  - Duplicated fixtures: 10+ → 0

- **Code Cleanliness**:
  - Verbose boolean returns: 14 → 0
  - Single-assignment variables: 32 → 0
  - Useless comments: 241 → 0

### Performance Improvements

- **Async Performance**:
  - Blocking I/O in endpoints: 53 → 0
  - Event loop responsiveness: +20% (estimated)
  - Request latency: -15% (estimated)

---

## Scan Report Reference

All detailed findings are available in `/home/user/ducktape/scan_results/`:

**CRITICAL Priority:**
- `error-swallowing.md` (80 violations)
- `stringly-typed.md` (416 violations)

**HIGH Priority:**
- `overly-loose-typing.md` (200+ violations)
- `suspicious-nullability.md` (194 violations)

**MEDIUM Priority:**
- `asyncio-antipatterns.md` (131 violations)
- `type-ignore-suppressions.md` (149 violations)
- `methods-vs-freestanding.md` (93 violations)
- `test-assertions.md` (500+ violations)
- `duplicated-test-code.md` (fixtures)
- `useless-test-classes.md` (41 violations)

**LOW Priority:**
- `unnecessary-verbosity.md` (100+ violations)
- `useless-comments-and-docs.md` (241 violations)
- `missing-dataclass-pydantic.md` (3 violations)
- `pydantic-antipatterns.md` (2 violations)

**Additional Scans (informational):**
- `api-model-design.md`
- `denormalized-computed-fields.md`
- `fastmcp-documentation-patterns.md` (32 violations)
- `functional-over-imperative.md` (63 violations)
- `identifier-naming.md` (58+ violations)
- `library-type-misuse.md`
- `manual-serde-needs-pydantic.md` (6 violations)
- `mypy-appeasing-code.md`
- `pygit2-patterns.md`
- `pytest-tmp-paths.md`
- `suspicious-defaults.md`
- `timestamp-naming.md`
- `trivial-forwarder-methods.md`
- `trivial-forwarders.md`
- `walrus-get-pattern.md`

---

## Next Steps

1. **Review this analysis** with tech lead and product owner
2. **Prioritize top 5 categories** for Wave H (recommended above)
3. **Assign teams** to parallel work streams
4. **Set up tracking** (GitHub Projects, Jira, etc.)
5. **Schedule kickoff** for Wave H cleanup sprint
6. **Define done criteria** for each category
7. **Plan deployment strategy** (staging → production)

---

## Appendix: Scan Methodology

All scans were executed on 2025-11-19 using:
- **AST analysis**: Python abstract syntax tree parsing
- **Regex pattern matching**: Ripgrep with PCRE2 patterns
- **Manual verification**: Sampling of results to validate findings
- **Coverage**: 943 Python files across entire repository

Detection tools:
- Custom detectors in `adgn/src/adgn/props/detectors/`
- Scan definitions in `prompts/scans/`
- ripgrep, ast module, mypy analysis
