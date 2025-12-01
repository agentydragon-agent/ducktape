# Test Patterns Analysis: OpenAI Mocks & Step Runners

**Analysis Date**: 2025-11-30
**Scope**: Tests using OpenAI mocks, MCP server mocks, and step-based test patterns

## Executive Summary

The design doc pattern (`test_scenario_steps.md`) has been **fully implemented** but **partially adopted**. Infrastructure exists and works well where used, but significant opportunities remain for:

1. **Eliminating `build_mcp_function` boilerplate** (33 files)
2. **Migrating `FakeOpenAIModel` usage** (5 files) to step runner pattern
3. **Centralizing assertion helpers** (currently duplicated/scattered)
4. **Creating reusable agent fixtures** (underutilized pattern)

---

## Implementation Status

### ✅ Implemented Infrastructure

All design doc components exist and work correctly:

| Component | Location | Status |
|-----------|----------|--------|
| `Step` Protocol | `tests/support/steps.py` | ✅ Complete |
| Step classes (`MakeCall`, `CheckThenCall`, etc.) | `tests/support/steps.py` | ✅ Complete |
| `_StepRunner` | `tests/support/responses.py` | ✅ Complete |
| `make_step_runner` fixture | `tests/conftest.py` | ✅ Complete |
| `make_mock()` helper | `tests/llm/support/openai_mock.py` | ✅ Complete |
| `ResponsesFactory` | `tests/support/responses.py` | ✅ Complete |

### 📊 Adoption Status

| Pattern | Files Using | Status | Notes |
|---------|-------------|--------|-------|
| `make_step_runner` (new) | **13 files** | ✅ Active use | Recommended pattern |
| `FakeOpenAIModel` (old) | **5 files** | ⚠️ Legacy | Migration candidates |
| `build_mcp_function` | **33 files** | ⚠️ Verbose | Should use typed MCP helpers instead |
| Step-based fixtures | **1 file** | 📈 Underutilized | Design doc recommends wider use |

---

## Detailed Findings

### 1. `build_mcp_function` Boilerplate (33 files)

**Problem**: Tests manually construct tool names and pass raw dicts for arguments.

**Current Pattern** (verbose):
```python
from adgn.mcp._shared.naming import build_mcp_function

responses_factory.make_tool_call(
    build_mcp_function("echo", "echo"),
    {"text": "hi"}
)
```

**Recommended Pattern** (typed, concise):
```python
from adgn.mcp.testing.simple_servers import EchoInput

MakeCall("echo", "echo", EchoInput(text="hi"))
```

**Benefits**:
- Type safety (Pydantic models)
- No manual name construction
- IDE autocomplete for arguments
- Compile-time validation

**Files affected**: 33 test files import `build_mcp_function`

---

### 2. `FakeOpenAIModel` Usage (5 files)

**Problem**: Old pattern requires manual response list construction and lacks automatic validation.

**Current Pattern** (old):
```python
from tests.llm.support.openai_mock import FakeOpenAIModel

client = FakeOpenAIModel([
    responses_factory.make_tool_call(...),
    responses_factory.make_assistant_message("done"),
])
# No automatic validation that all responses were consumed
```

**Recommended Pattern** (new):
```python
from tests.llm.support.openai_mock import make_mock

runner = make_step_runner(steps=[
    MakeCall("echo", "echo", EchoInput(text="hi")),
    AssistantMessage("done"),
])
client = make_mock(runner.handle_request_async)
# Automatic validation via fixture teardown
```

**Benefits**:
- Automatic step completion validation
- Clearer test scenario structure
- Fails early if steps don't match execution
- Consistent with rest of test suite

**Files to migrate**:
1. `tests/llm/cli/test_llm_edit_cli.py`
2. `tests/agent/conftest.py` (in helper functions)
3. `tests/props/conftest.py` (in helper functions)
4. `tests/llm/support/openai_mock.py` (example in docstring)
5. `tests/props/prompt_eval/README.md` (docs)

---

### 3. Assertion Helpers (Scattered)

**Problem**: Critical assertion helpers are defined in integration test file and imported by Step classes.

**Current State**:
- **Location**: `tests/props/prompt_eval/test_prompt_optimizer_integration.py` (lines 59-150)
- **Helpers**: `extract_structured_content`, `get_last_function_output`, `assert_last_call`, `extract_output`, `assert_and_extract`
- **Imports**: Step classes (`CheckThenCall`, `ExtractThenCall`, `Finish`) import from integration test

**Issues**:
1. **Circular dependency risk**: Step classes (in `tests/support/`) import from specific test file
2. **Duplication**: 150+ lines of extraction/assertion code in integration test
3. **Discoverability**: Helpers hidden in test file, not in `tests/support/`
4. **Coupling**: Changes to integration test can break Step classes

**Recommended Structure**:
```
tests/support/
├── assertions.py          # NEW: assert_last_call, assert_and_extract
├── extraction.py          # NEW: extract_structured_content, get_last_function_output
├── responses.py           # EXISTING: ResponsesFactory, _StepRunner
└── steps.py              # EXISTING: Step classes (import from assertions.py)
```

**Migration**:
1. Create `tests/support/assertions.py` with all assertion helpers
2. Create `tests/support/extraction.py` with extraction helpers
3. Update Step classes to import from new locations
4. Remove duplicated code from `test_prompt_optimizer_integration.py`

---

### 4. Reusable Agent Fixtures (Underutilized)

**Design Doc Recommendation**: Create fixtures for common agent step sequences.

**Current State**:
- ✅ **Good example**: `test_prompt_optimizer_integration.py` (if it existed as fixture)
- ❌ **Missed opportunity**: Most tests inline step sequences instead of reusing fixtures

**Recommended Pattern** (from design doc):
```python
@pytest.fixture
def po_agent_steps() -> Sequence[Step]:
    """Standard PO agent workflow: docker exec → upsert → critic → grader."""
    return [
        MakeCall("docker", "exec", ExecInput(...)),
        CheckThenCall("docker_exec", "prompt_eval", "upsert_prompt", UpsertPromptInput(...)),
        ExtractThenCall("prompt_eval_upsert_prompt", UpsertPromptOutput,
                       lambda out: ("prompt_eval", "run_critic", CriticInput(..., sha=out.prompt_sha256))),
        ExtractThenCall("prompt_eval_run_critic", RunCriticOutput,
                       lambda out: ("prompt_eval", "run_grader", RunGraderInput(..., id=out.critique_id))),
        Finish("prompt_eval_run_grader"),
    ]

@pytest.fixture
def po_agent(make_step_runner, po_agent_steps) -> _StepRunner:
    """Ready-to-use PO agent runner."""
    return make_step_runner(steps=po_agent_steps)
```

**Benefits**:
- DRY: Reuse common sequences across tests
- Composable: Mix and match agent fixtures
- Testable: Step sequences can be tested independently
- Maintainable: Change sequence in one place

**Opportunity**: Identify common patterns in current tests and extract to fixtures.

---

### 5. Ad-hoc Mock Patterns

**Finding**: Some tests use different mocking approaches instead of step runner pattern.

**Example**: `test_compaction.py`
```python
class MockOpenAIClient:
    def __init__(self):
        self.model = "gpt-4o-mini-test"
        self.responses_create = AsyncMock()

    async def setup_summary_response(self, summary_text: str):
        mock_response = Mock()
        mock_response.output = [AssistantMessageOut(...)]
        self.responses_create.return_value = mock_response
```

**Question**: Could this use step runner pattern instead?

**Analysis**:
- `test_compaction.py` tests compaction handler, not multi-turn agent behavior
- Single response mocking is simpler for unit-style tests
- Step runner might be overkill here

**Recommendation**:
- Keep `AsyncMock` for unit tests (single interactions)
- Use step runner for integration tests (multi-turn scenarios)
- Document the distinction in test guidelines

---

## Refactoring Opportunities

### Priority 1: High Impact, Low Risk

1. **Centralize assertion helpers** (estimated 2-3 hours)
   - Create `tests/support/assertions.py` and `extraction.py`
   - Move helpers from integration test
   - Update imports in Step classes
   - **Impact**: Eliminates circular dependency, improves discoverability
   - **Risk**: Low (pure refactoring, behavior unchanged)

2. **Migrate `FakeOpenAIModel` to step runner** (estimated 1-2 hours)
   - 5 files to update
   - Pattern is mechanical transformation
   - **Impact**: Consistent mocking pattern across all tests
   - **Risk**: Low (step runner is battle-tested)

### Priority 2: Medium Impact, Medium Effort

3. **Eliminate `build_mcp_function` usage** (estimated 4-6 hours)
   - 33 files to update
   - Convert dict args to Pydantic models
   - Some test MCP servers may need Pydantic input models added
   - **Impact**: Type safety, better errors, cleaner tests
   - **Risk**: Medium (requires ensuring all MCP test servers have input models)

4. **Extract reusable agent fixtures** (estimated 3-4 hours)
   - Identify common step sequences (e.g., PO agent, critic agent)
   - Extract to conftest fixtures
   - Update tests to use fixtures
   - **Impact**: DRY, easier test maintenance
   - **Risk**: Low-Medium (requires careful analysis of commonality)

### Priority 3: Nice-to-Have

5. **Document mock pattern guidelines** (estimated 1 hour)
   - When to use step runner vs AsyncMock
   - When to use fixtures vs inline steps
   - Examples of each pattern
   - **Impact**: Developer onboarding, consistency
   - **Risk**: None (documentation only)

---

## Specific File Analysis

### Files Using Step Runner (✅ Good Examples)

| File | Pattern | Notes |
|------|---------|-------|
| `test_agent_mcp_echo.py` | ✅ Clean step runner usage | Good example of simple 2-step test |
| `test_with_mocks.py` | ✅ Parametrized (mock/live) | Shows LIVE pattern integration |
| `test_flat_tools_schema.py` | ✅ Multi-phase testing | Shows phase-based testing with step runner |
| `test_prompt_optimizer_integration.py` | ✅ Complex multi-agent | Excellent example, but helpers should move |

### Files Using FakeOpenAIModel (⚠️ Migration Candidates)

| File | Usage | Migration Effort |
|------|-------|------------------|
| `test_llm_edit_cli.py` | Simple 1-response mock | Easy (10 minutes) |
| `tests/agent/conftest.py` | Helper function `make_test_agent` | Medium (affects multiple tests) |
| `tests/props/conftest.py` | Legacy fixtures | Medium (need usage analysis) |

### Files Using build_mcp_function (⚠️ Verbose)

**Sample (33 total)**:
- `test_messages_forwarding.py` - 3 usages
- `test_parallel_calls.py` - Multiple usages
- `test_exec_roundtrip.py` - Multiple usages
- `test_mcp_integration.py` - Multiple usages
- ... (29 more files)

**Common Pattern**:
```python
# Old
responses_factory.tool_call(build_mcp_function("echo", "echo"), {"text": "hi"})

# New
responses_factory.mcp_tool_call("echo", "echo", EchoInput(text="hi"))
```

Note: `ResponsesFactory` already has `mcp_tool_call` method that handles naming!

---

## Oververbose Documentation Cases

### 1. test_prompt_optimizer_integration.py (600+ lines)

**Issue**: 150+ lines of helper functions that should be in shared test support.

**Breakdown**:
- Lines 1-58: Imports and setup (reasonable)
- Lines 59-150: **Extraction/assertion helpers** (should move to `tests/support/`)
- Lines 151+: Actual test fixtures and tests

**Estimated Reduction**: ~25% shorter after helper extraction

### 2. Redundant Type Annotations

**Current**:
```python
T = TypeVar("T", bound=BaseModel)

def extract_structured_content(item: FunctionCallOutputItem, output_type: type[T]) -> T:
    """Extract and parse structured content from MCP tool result.

    The output field contains a JSON-serialized CallToolResult with the actual
    tool output either in structured_content or in content[0].text (as JSON).

    Args:
        item: FunctionCallOutputItem containing the MCP result
        output_type: Pydantic model class to parse the structured content as

    Returns:
        Parsed and validated instance of output_type
    """
    # 40 lines of implementation
```

**Issue**: Docstring repeats what signature already says (type annotations are self-documenting).

**Shorter**:
```python
def extract_structured_content(item: FunctionCallOutputItem, output_type: type[T]) -> T:
    """Extract and parse structured MCP tool output (handles both structured_content and content[0].text)."""
    # 40 lines of implementation
```

### 3. Design Doc vs Implementation Gap

**Design doc shows**: Concise examples (9 lines for agent setup)

**Actual usage**: Often more verbose due to:
- Missing shared fixtures
- Inlined step sequences
- Manual tool name construction

**Example Gap**:

**Design doc**:
```python
runner = make_step_runner(steps=[...])  # 5 steps
client = make_mock(runner.handle_request_async)
```

**Actual**:
```python
# Often includes:
from adgn.mcp._shared.naming import build_mcp_function
# Manual tool name construction
# Dict arguments instead of Pydantic
# No fixture reuse
```

---

## Recommendations Summary

### Immediate Actions (Week 1)

1. ✅ **Centralize assertion helpers**
   - Move to `tests/support/assertions.py` and `extraction.py`
   - Update Step class imports
   - Document in `tests/support/README.md`

2. ✅ **Migrate FakeOpenAIModel** (5 files)
   - Low risk, high consistency gain
   - Can be done file-by-file

### Short-term (Sprint)

3. ✅ **Eliminate build_mcp_function** (33 files)
   - Use `ResponsesFactory.mcp_tool_call()` instead
   - Add Pydantic input models where missing
   - Update examples in docs

4. ✅ **Extract reusable fixtures**
   - Start with most common patterns (e.g., PO agent)
   - Document pattern in design doc

### Medium-term (Quarter)

5. ✅ **Documentation cleanup**
   - Add test pattern guidelines
   - Update examples to show current best practices
   - Create migration guide for old → new patterns

6. ✅ **Tool audits**
   - Regular reviews for pattern consistency
   - Pre-commit hook to flag `build_mcp_function` in new code?

---

## Metrics for Success

| Metric | Current | Target |
|--------|---------|--------|
| Files using step runner | 13 | 18+ (all mock tests) |
| Files using `FakeOpenAIModel` | 5 | 0 |
| Files using `build_mcp_function` | 33 | 0 (except in `_shared.naming` itself) |
| Shared assertion helpers | 0 files | 2 files (`assertions.py`, `extraction.py`) |
| Reusable agent fixtures | ~1 | 3-5 |
| Test pattern documentation | Minimal | Comprehensive guide |

---

## Appendix: File Lists

### Files Using make_step_runner (13)
1. `tests/props/prompt_eval/test_prompt_optimizer_integration.py`
2. `tests/props/cli_app/test_lint_issue_bootstrap.py`
3. `tests/agent/e2e/test_approvals.py`
4. `tests/agent/e2e/test_ui.py`
5. `tests/agent/e2e/test_proposals_reject.py`
6. `tests/agent/e2e/test_notifications_handler.py`
7. `tests/mcp/approval_policy/test_server_available.py`
8. `tests/agent/test_mcp_resources_flow.py`
9. `tests/agent/test_agent_mcp_echo.py`
10. `tests/agent/test_with_mocks.py`
11. `tests/agent/test_flat_tools_schema.py`
12. `tests/agent/test_approval_integration.py`
13. `tests/conftest.py` (fixture definition)

### Files Using FakeOpenAIModel (5)
1. `tests/llm/support/openai_mock.py` (definition)
2. `tests/agent/conftest.py`
3. `tests/props/conftest.py`
4. `tests/llm/cli/test_llm_edit_cli.py`
5. `tests/props/prompt_eval/README.md` (docs)

### Files Using build_mcp_function (33)
*See grep output - includes test files across agent/, mcp/, llm/ suites*
