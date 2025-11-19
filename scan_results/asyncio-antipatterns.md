# Code Quality Scan: Asyncio Antipatterns

**Scan Date**: 2025-11-19
**Target Codebase**: /home/user/ducktape
**Python Version Required**: 3.11+ (for TaskGroup support)
**Current Python Version**: 3.11.14 ✓

## Summary

This scan identified asyncio antipatterns and code quality issues across the codebase:

- **19 files** using `asyncio.gather()` (potential TaskGroup candidates)
- **112 unnecessary `@pytest.mark.asyncio` decorators** (in projects with `asyncio_mode = "auto"`)
- **53 async functions** with blocking I/O operations
- **0 instances** of deprecated `asyncio.get_event_loop()`
- **0 nested `asyncio.run()` calls** (outside main entry points)

## Detailed Findings

### 1. asyncio.gather() Usage (19 files, Python 3.11+ candidate for TaskGroup)

These instances use `asyncio.gather()` which could benefit from `asyncio.TaskGroup` for better structured concurrency, exception handling, and code clarity (Python 3.11+).

#### High Priority (with `return_exceptions=True` - error handling pattern)

| File | Line | Pattern | Notes |
|------|------|---------|-------|
| /home/user/ducktape/adgn/src/adgn/agent/server/runtime.py | 171 | `await asyncio.gather(*tasks, return_exceptions=True)` | Flushes background tasks with exception handling |
| /home/user/ducktape/adgn/src/adgn/agent/persist/handler.py | 71 | `results = await asyncio.gather(*pending, return_exceptions=True)` | Collects persistence errors |
| /home/user/ducktape/claude/claude_optimizer/tests/test_full_e2e_workflow.py | 163 | `results = await asyncio.gather(*tasks, return_exceptions=True)` | Test orchestration |
| /home/user/ducktape/adgn/src/adgn/props/prompt_eval/server.py | 231 | `results = await asyncio.gather(*[one(s) for s in specimens], return_exceptions=True)` | Evaluates specimens with failure handling |
| /home/user/ducktape/adgn/src/adgn/git_commit_ai/cli.py | 371,380 | Two calls with different patterns | AI commit + precommit hook orchestration |
| /home/user/ducktape/adgn/src/adgn/mcp/notifying_fastmcp.py | 173,198,207 | Multiple broadcast calls | Resource notifications with exception handling |
| /home/user/ducktape/experimental/ember_evals/runner.py | 417 | `results = await asyncio.gather(*(...), return_exceptions=True)` | Eval runner with failure collection |
| /home/user/ducktape/experimental/cotrl/llm_rl_experiment.py | 508 | `results = await asyncio.gather(*tasks, return_exceptions=True)` | RL experiment batch runs |

**Recommendation**: These patterns are candidates for `asyncio.TaskGroup` when:
- Need to run multiple tasks concurrently ✓
- Want automatic cancellation on first error (use default TaskGroup behavior, or wrap in try/except for capture-all)
- Tasks update shared state dictionaries/objects

Consider this refactoring pattern:
```python
# Before (gather with manual exception handling)
results = await asyncio.gather(*tasks, return_exceptions=True)
errors = [r for r in results if isinstance(r, Exception)]

# After (TaskGroup with structured exception handling)
async with asyncio.TaskGroup() as tg:
    for task in tasks:
        tg.create_task(task)
```

#### Standard Usage (no special error handling)

| File | Line | Pattern | Usage |
|------|------|---------|-------|
| /home/user/ducktape/wt/src/wt/server/handlers/status_handler.py | 200 | `await asyncio.gather(*[process_single_worktree(p) for p in worktree_paths])` | Status gathering for multiple worktrees |
| /home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/habitify_client.py | 296 | `results = await asyncio.gather(*tasks)` | Task completion with exception propagation |
| /home/user/ducktape/adgn/tests/agent/persist/test_integration.py | 567 | `await asyncio.gather(*tasks)` | Test concurrent save operations |
| /home/user/ducktape/adgn/tests/agent/test_policy_state_management.py | 227 | `await asyncio.gather(*[update_policy(i) for i in range(10)])` | Test concurrent updates |
| /home/user/ducktape/adgn/src/adgn/llm/sysrw/extract_dataset_ccr.py | 91 | `results: list[list[dict]] = await asyncio.gather(*[wrapped(p) for p in files])` | Dataset extraction |
| /home/user/ducktape/adgn/src/adgn/llm/sysrw/extract_dataset.py | 29 | `results: list[list[dict]] = await asyncio.gather(*[wrapped(p) for p in files])` | Dataset processing |
| /home/user/ducktape/adgn/src/adgn/props/cli_app/main.py | 513 | `rows: list[dict[str, Any]] = await asyncio.gather(*[one(s) for s in specimens])` | Specimen result gathering |
| /home/user/ducktape/adgn/src/adgn/props/eval_harness.py | 576 | `entries = await asyncio.gather(*[_run_one(s) for s in SAMPLES])` | Evaluation harness |
| /home/user/ducktape/adgn/src/adgn/props/cluster_unknowns.py | 180 | `await asyncio.gather(*tasks)` | Clustering operations |
| /home/user/ducktape/adgn/mcp/exec/seatbelt.py | 163 | `await asyncio.wait_for(asyncio.gather(stdout_task, stderr_task), timeout=t1)` | Process stream handling with timeout |
| /home/user/ducktape/adgn/src/adgn/agent/mcp_bridge/cli.py | 180 | `await asyncio.gather(mcp_server.serve(), ui_server.serve())` | Server startup coordination |

**Recommendation**: Standard uses can be converted to `TaskGroup` for cleaner cancellation behavior on exceptions.

---

### 2. Unnecessary @pytest.mark.asyncio Decorators

**Status**: 112 instances found (109 in adgn, 3 in claude_optimizer)

**Configuration**: Projects have `asyncio_mode = "auto"` enabled:
- ✓ /home/user/ducktape/adgn/pyproject.toml
- ✓ /home/user/ducktape/mcp_starter/pyproject.toml
- ✓ /home/user/ducktape/claude/claude_optimizer/pyproject.toml
- ✓ /home/user/ducktape/gatelet/pyproject.toml
- ✓ /home/user/ducktape/experimental/dbus_fast_example/pyproject.toml
- ✓ /home/user/ducktape/homeassistant/iaqi/pyproject.toml
- ✓ /home/user/ducktape/llm/mcp/habitify/habitify_mcp_server/pytest.ini

**Issue**: When `asyncio_mode = "auto"` is configured, pytest automatically detects `async def test_*()` functions without requiring explicit `@pytest.mark.asyncio` decorators. The decorators are redundant.

#### Examples in adgn (109 total)

- /home/user/ducktape/adgn/tests/agent/test_policy_validation_reload.py: 7 decorators (lines 41, 57, 74, 91, 113, 129, 143)
- /home/user/ducktape/adgn/tests/agent/persist/test_sqlite_tool_calls.py: 3 decorators (lines 34, 61, 91)
- /home/user/ducktape/adgn/tests/agent/persist/test_integration.py: Multiple decorators
- /home/user/ducktape/adgn/tests/agent/server/test_mcp_routing.py: Multiple decorators
- /home/user/ducktape/adgn/tests/agent/test_policy_state_management.py: Multiple decorators
- (95+ more across adgn/tests)

#### Examples in claude_optimizer (3 total)

- /home/user/ducktape/claude/claude_optimizer/tests/test_optimizer.py: 3 decorators (lines 60, 90, 183)

**Recommendation**: Remove all `@pytest.mark.asyncio` decorators from test functions in projects with `asyncio_mode = "auto"` configured.

**Fix Strategy**:
```bash
# For each test file, remove decorators like:
# @pytest.mark.asyncio
# async def test_something():

# Example (adgn/tests):
rg --type py '@pytest\.mark\.asyncio' adgn/tests/ --replace '' --files-with-matches
```

**Benefits**:
- Cleaner test code
- Automatic detection of any new async test without manual decorator addition
- No behavioral change (pytest-asyncio auto-detection is identical)

---

### 3. Blocking I/O in Async Functions

**Severity**: HIGH - These operations block the event loop

**Total Findings**: 53 async functions with blocking I/O

#### Category A: Path.read_text() / Path.write_text() (18 files)

These perform synchronous file I/O in async contexts:

| File | Lines | Async Function | Blocking Operation |
|------|-------|----------------|-------------------|
| /home/user/ducktape/llm/html/llm_html/server.py | 127, 157 | `async def index()` (line 124) | `Path("index.md").read_text()` |
| /home/user/ducktape/llm/html/llm_html/server.py | 277 | `async def serve_markdown_page()` (line 154) | `Path(f"{page}.md").read_text()` |
| /home/user/ducktape/llm/html/llm_html/server.py | 277 | (another async function) | File operations |
| /home/user/ducktape/adgn/src/adgn/seatbelt/runner.py | 291, 309 | `async def __aexit__()` | open() calls in context manager |
| /home/user/ducktape/adgn/src/adgn/agent/persist/sqlite.py | Multiple lines | Multiple async functions | SQL file read operations (18 instances) |
| /home/user/ducktape/adgn/src/adgn/llm/sysrw/extract_dataset_ccr.py | 40 | `async def extract()` | `path.read_text()` |
| /home/user/ducktape/adgn/src/adgn/llm/sysrw/run_eval.py | 107 | Async evaluation | File I/O |
| /home/user/ducktape/adgn/src/adgn/mcp/chat/server.py | 182,191,202,215,237 | Multiple async resources | File reads for chat context |
| /home/user/ducktape/adgn/src/adgn/openai_utils/http_logging.py | 37 | Async HTTP logging | File operations |
| /home/user/ducktape/wt/src/wt/client/handlers.py | 239 | Async handler | File I/O |
| /home/user/ducktape/wt/src/wt/client/wt_client.py | 93, 223 | Async client methods | Configuration file reading |
| /home/user/ducktape/experimental/cotrl/llm_rl_experiment.py | 170,189,207 | Async experiment runners | Policy/config file reads |
| /home/user/ducktape/experimental/ember_evals/runner.py | 159 | Async evaluation | File operations |
| /home/user/ducktape/gatelet/gatelet/server/test_admin_webhook_e2e.py | 30 | Async test | File I/O |
| /home/user/ducktape/claude/claude_optimizer/graders/generic_graders.py | 90 | Async grading | File operations |
| /home/user/ducktape/adgn/tests (multiple conftest.py files) | Multiple | Async fixtures | Configuration/test data files |

**Example - High Priority**:
```python
# /home/user/ducktape/llm/html/llm_html/server.py:124-127
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page with rendered markdown."""
    try:
        text = Path("index.md").read_text()  # ❌ BLOCKING I/O
        # ... rest of function
```

**Fix Strategy**:

1. **For simple one-shot file reads** → Use `asyncio.to_thread()`:
```python
text = await asyncio.to_thread(Path("index.md").read_text)
```

2. **For repeated file operations** → Use `aiofiles`:
```python
import aiofiles
async with aiofiles.open("index.md", "r") as f:
    text = await f.read()
```

3. **For configuration files** → Load once at startup (sync), cache in async functions

---

### 4. Deprecated APIs

**Status**: PASS ✓

- No instances of `asyncio.get_event_loop()` found
- No nested `asyncio.run()` calls detected

---

## Recommendations by Priority

### Priority 1: Fix Blocking I/O (Event Loop Impact)

1. **Critical files** (high traffic paths):
   - /home/user/ducktape/llm/html/llm_html/server.py (web server endpoints)
   - /home/user/ducktape/adgn/src/adgn/mcp/chat/server.py (MCP resource handlers)

2. **Implementation**:
   - Replace `Path(...).read_text()` → `await asyncio.to_thread(Path(...).read_text)`
   - Or migrate to `aiofiles` for better async semantics

### Priority 2: Modernize Pytest Tests (Code Cleanliness)

1. **Scope**: 112 `@pytest.mark.asyncio` decorators across adgn and claude_optimizer tests
2. **Effort**: Low (automated removal)
3. **Impact**: Cleaner codebase, no functional change

### Priority 3: Refactor asyncio.gather() to TaskGroup (Python 3.11+ Best Practices)

1. **Start with exception-handling patterns** (8 files with `return_exceptions=True`)
2. **Progress to standard patterns** (11 files with simple gather usage)
3. **Benefit**: Automatic cancellation, better exception propagation, clearer intent

---

## Configuration Reference

### Projects with asyncio_mode = "auto"

These projects can safely remove `@pytest.mark.asyncio` decorators:

```
adgn/pyproject.toml                                    ✓ 109 decorators found
mcp_starter/pyproject.toml                             ✓ 0 decorators (clean)
claude/claude_optimizer/pyproject.toml                 ✓ 3 decorators found
gatelet/pyproject.toml                                 ✓ 0 decorators (clean)
experimental/dbus_fast_example/pyproject.toml          ✓ Not checked
homeassistant/iaqi/pyproject.toml                      ✓ Not checked
llm/mcp/habitify/habitify_mcp_server/pytest.ini        ✓ Not checked (habitify_client.py has gather at 296)
```

---

## Action Items

```
[ ] 1. Remove 109 @pytest.mark.asyncio decorators in adgn/tests
[ ] 2. Remove 3 @pytest.mark.asyncio decorators in claude/claude_optimizer/tests
[ ] 3. Fix blocking I/O in /home/user/ducktape/llm/html/llm_html/server.py (3 async functions)
[ ] 4. Fix blocking I/O in /home/user/ducktape/adgn/src/adgn/seatbelt/runner.py (2 async methods)
[ ] 5. Audit adgn/src/adgn/agent/persist/sqlite.py (18 blocking I/O instances)
[ ] 6. Refactor asyncio.gather() in 8 high-priority files (with return_exceptions=True)
[ ] 7. Refactor asyncio.gather() in 11 standard-usage files to TaskGroup (Python 3.11+)
[ ] 8. Review blocking I/O in MCP chat server resource handlers
```

---

## Notes

- Python 3.11.14 is available, enabling full TaskGroup support
- No deprecated `asyncio.get_event_loop()` usage found (✓ good)
- Blocking I/O is the primary concern affecting event loop responsiveness
- pytest-asyncio `asyncio_mode = "auto"` is correctly configured; decorators are purely redundant
