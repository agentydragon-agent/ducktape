# Test Scenario Steps Pattern

## Problem

Test agents currently use imperative if/elif chains to define multi-turn interactions:

```python
def _handle_turn(self, req: ResponsesRequest) -> ResponsesResult:
    if self.turn == 1:
        return self.factory.make_tool_call(...)
    if self.turn == 2:
        assert_last_call(req, "docker_exec")
        return self.factory.make_tool_call(...)
    if self.turn == 3:
        result = assert_and_extract(req, "tool", OutputType)
        return self.factory.make_tool_call(..., value=result.field)
    if self.turn == 4:
        assert_last_call(req, "other_tool")
        return self.factory.make_assistant_message("Done")
    raise RuntimeError(f"Unexpected turn {self.turn}")
```

**Issues:**
- Magic turn numbers disconnected from max_turns
- Repetitive assertion boilerplate
- Hard to see test scenario at a glance
- Runtime errors if turn count changes
- Duplicated `_handle_turn` logic across all subclasses

## Solution: Declarative Step Lists

Define test scenarios as data, not control flow:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from adgn.openai_utils.model import ResponsesRequest, ResponsesResult
from tests.support.responses import ResponsesFactory


class Step(Protocol):
    """Protocol for step objects that can be executed in sequence."""

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        ...


@dataclass
class MakeCall:
    """Initial turn: make a tool call."""
    server: str
    tool: str
    args: BaseModel

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_mcp_tool_call(self.server, self.tool, self.args)


@dataclass
class CheckThenCall:
    """Assert previous tool completed, then call next."""
    expected_tool: str
    server: str
    tool: str
    args: BaseModel

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_last_call(req, self.expected_tool)
        return factory.make_mcp_tool_call(self.server, self.tool, self.args)


@dataclass
class ExtractThenCall:
    """Extract typed output from previous call, use in next call."""
    expected_tool: str
    output_type: type[BaseModel]
    make_next: Callable[[BaseModel], tuple[str, str, BaseModel]]

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        output = assert_and_extract(req, self.expected_tool, self.output_type)
        server, tool, args = self.make_next(output)
        return factory.make_mcp_tool_call(server, tool, args)


@dataclass
class Finish:
    """Final turn: assert completion and return message."""
    expected_tool: str
    message: str = "Done"

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        assert_last_call(req, self.expected_tool)
        return factory.make_assistant_message(self.message)


@dataclass
class AssistantMessage:
    """Return assistant message without checking previous tool.

    Use for simple sequences where you don't need to validate tool completion.
    For complex workflows, prefer Finish which validates the final tool.
    """
    message: str

    def execute(self, req: ResponsesRequest, factory: ResponsesFactory) -> ResponsesResult:
        return factory.make_assistant_message(self.message)
```

## Factory Integration

Add internal runner class and factory fixture:

```python
from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from adgn.openai_utils.model import ResponsesRequest, ResponsesResult


class _StepRunner:
    """Generic state machine driven by declarative steps.

    Use as a context manager to get automatic validation that all steps completed:
        with _StepRunner(factory, steps) as runner:
            # Use runner
            pass
        # Validates all steps executed on exit
    """

    def __init__(self, factory: ResponsesFactory, steps: Sequence[Step]) -> None:
        self.factory: ResponsesFactory = factory
        self.steps: Sequence[Step] = steps
        self.turn: int = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Only validate if no exception occurred during test
        if exc_type is None and self.turn != len(self.steps):
            pytest.fail(f"Step runner incomplete: executed {runner.turn}/{len(runner.steps)} steps")
        return False

    def handle_request(self, req: ResponsesRequest) -> ResponsesResult:
        """Main entry point - checks bounds and executes current step."""
        if self.turn >= len(self.steps):
            pytest.fail(f"Exceeded {len(self.steps)} expected turns (got turn {self.turn + 1})")
        result = self.steps[self.turn].execute(req, self.factory)
        self.turn += 1
        return result

    async def handle_request_async(self, req: ResponsesRequest) -> ResponsesResult:
        """Async wrapper for handle_request."""
        return self.handle_request(req)


@pytest.fixture
def make_step_runner(responses_factory: ResponsesFactory) -> Callable[[Sequence[Step]], _StepRunner]:
    """Factory fixture that creates step runners.

    Returns a factory function that creates _StepRunner instances.
    Each runner is a context manager that validates all steps completed.

    Usage:
        def test_workflow(make_step_runner):
            with make_step_runner(steps=[...]) as runner:
                # Use runner
                pass
            # Validation happens automatically on context exit

        def test_multiple_agents(make_step_runner):
            with make_step_runner(steps=[...]) as agent1, \
                 make_step_runner(steps=[...]) as agent2:
                # Use both agents
                pass
    """
    def _make(steps: Sequence[Step]) -> _StepRunner:
        return _StepRunner(factory=responses_factory, steps=steps)

    return _make
```

## Usage

Use the fixture to create state machines with automatic completion checking:

```python
async def test_multi_stage_workflow(make_step_runner):
    """Test demonstrates multiple agent stages with automatic validation."""

    # Define PO agent steps
    po_agent = make_step_runner(steps=[
        MakeCall("docker", "exec", ExecInput(cmd=["cat", "prompt.txt"], timeout_ms=30000)),
        CheckThenCall("docker_exec", "prompt_eval", "upsert_prompt",
                     UpsertPromptInput(file_path="/workspace/prompt-v1.txt")),
        ExtractThenCall("prompt_eval_upsert_prompt", UpsertPromptOutput,
                       lambda out: ("prompt_eval", "run_critic",
                                   CriticInput(specimen_slug="test", prompt_sha256=out.prompt_sha256))),
        ExtractThenCall("prompt_eval_run_critic", RunCriticOutput,
                       lambda out: ("prompt_eval", "run_grader",
                                   RunGraderInput(critique_id=out.critique_id))),
        Finish("prompt_eval_run_grader"),
    ])

    # Define critic agent steps
    critic_agent = make_step_runner(steps=[
        MakeCall("critic_submit", "upsert_issue", UpsertIssueInput(issue_id="test-001", ...)),
        CheckThenCall("critic_submit_upsert_issue", "critic_submit", "add_occurrence", ...),
        Finish("critic_submit_add_occurrence"),
    ])

    # Run test with mock LLM using these agents
    mock = WorkflowMock([po_agent, critic_agent])
    await run_optimizer(mock)

    # Fixture automatically validates all steps completed for both agents
```

## Benefits

| Before | After |
|--------|-------|
| Magic turn numbers | Self-documenting step list |
| `max_turns=5` separate from logic | No `max_turns` - derived from `len(steps)` |
| Repetitive if/elif/raise | Fixture: `make_step_runner(steps)` |
| One subclass per scenario | No subclasses - just data |
| Agent name tracking | No bookkeeping - pytest traceback is sufficient |
| Hard to see full scenario | Entire test flow visible upfront |
| Runtime turn errors | Compile-time type checking |
| Imperative control flow | Declarative data |
| Manual completion checking | Automatic validation all steps executed |

## Unified Pattern

All tests use the same pattern - create a runner and wrap it with `make_mock()`:

```python
from tests.llm.support.openai_mock import make_mock
from adgn.mcp.testing.simple_servers import EchoInput

# Before: Manual FakeOpenAIModel construction
client = FakeOpenAIModel([
    responses_factory.make_tool_call(build_mcp_function("echo", "echo"), {"text": "hi"}),
    responses_factory.make_assistant_message("done"),
])

# After: Declarative steps with automatic validation (works for ALL sequences)
runner = make_step_runner(steps=[
    MakeCall("echo", "echo", EchoInput(text="hi")),
    AssistantMessage("done"),
])
client = make_mock(runner.handle_request_async)
```

**Benefits:**
- **One pattern** for all test scenarios (simple and complex)
- Removes `build_mcp_function` boilerplate
- Removes `FakeOpenAIModel` wrapper construction
- **Automatic validation** that all steps executed
- Type-safe: all args are Pydantic models
- **Request capture**: `client.captured` records all requests

### Complex Example

Same pattern works for complex sequences with assertions and data extraction:

```python
from adgn.mcp.exec.models import ExecInput
from tests.llm.support.openai_mock import make_mock

runner = make_step_runner(steps=[
    MakeCall("docker", "exec", ExecInput(...)),
    CheckThenCall("docker_exec", "prompt_eval", "upsert_prompt", UpsertPromptInput(...)),
    ExtractThenCall("prompt_eval_upsert_prompt", UpsertPromptOutput,
                   lambda out: ("prompt_eval", "run_critic", CriticInput(..., sha=out.prompt_sha256))),
    Finish("prompt_eval_run_critic"),
])
client = make_mock(runner.handle_request_async)

# Can inspect requests
assert len(client.captured) == 4
```

## Design Notes

### All args must be Pydantic BaseModel

**Enforced rule:** All step types that take `args` require `BaseModel`, never dicts.

**Import from production MCP servers:**
```python
# Production servers already have Pydantic flat models
from adgn.mcp.exec.models import ExecInput
from adgn.mcp.git_ro.server import StatusInput, DiffInput, ShowInput
from adgn.props.mcp.servers import UpsertPromptInput, CriticInput, RunGraderInput

mock = make_step_runner(steps=[
    MakeCall("docker", "exec", ExecInput(cmd=["cat", "file.txt"], timeout_ms=30000)),
    AssistantMessage("done"),
])
```

**For test helper servers:**
Import from `adgn.mcp.testing.simple_servers`:

```python
# Test servers also use flat Pydantic models
from adgn.mcp.testing.simple_servers import EchoInput

mock = make_step_runner(steps=[
    MakeCall("echo", "echo", EchoInput(text="test")),
    AssistantMessage("done"),
])
```

This keeps the pattern pure and provides type safety everywhere.

### Why execute() takes factory, not state

Step classes receive `factory: ResponsesFactory` rather than `state: AgentStateBase`:

- **Minimal coupling**: Steps only need the factory to build responses
- **Stateless**: Steps are pure data; no hidden references to mutable state
- **Testable**: Steps can be tested in isolation with different factories
- **Clear dependencies**: Explicit parameter shows exactly what each step needs

If a step needed turn context, we could pass `state`, but current patterns don't require it.

### Step sequences as fixtures

When step sequences are reused across tests, make them fixtures:

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


@pytest.fixture
def critic_agent(make_step_runner) -> _StepRunner:
    """Ready-to-use Critic agent runner."""
    return make_step_runner(steps=[
        MakeCall("critic_submit", "upsert_issue", UpsertIssueInput(...)),
        CheckThenCall("critic_submit_upsert_issue", "critic_submit", "add_occurrence", ...),
        Finish("critic_submit_add_occurrence"),
    ])


def test_optimizer_with_agents(po_agent, critic_agent):
    """Test using ready-made agent fixtures."""
    mock = WorkflowMock([po_agent, critic_agent])
    await run_optimizer(mock)
    # Fixture automatically validates both agents completed all steps


@pytest.fixture
def workflow_mock(po_agent, critic_agent, grader_agent):
    """Complete workflow mock with all three standard agents."""
    return WorkflowMock([po_agent, critic_agent, grader_agent])


async def test_full_workflow(workflow_mock):
    """Test using complete workflow fixture - cleanest option."""
    await run_optimizer(workflow_mock)
    # All three agents automatically validated for completion
```

## Step Types Reference

### MakeCall
**Use:** First turn, no previous call to check
**Pattern:** Make a tool call with Pydantic args

### CheckThenCall
**Use:** Previous call finished, output not needed
**Pattern:** Assert previous tool → call next tool

### ExtractThenCall
**Use:** Previous call's output feeds next call
**Pattern:** Assert + extract typed output → use in next call

### Finish
**Use:** Last turn in complex workflow
**Pattern:** Assert final tool completed → return message

### AssistantMessage
**Use:** Return text in simple sequences
**Pattern:** Return message without tool validation
**Note:** For complex workflows, prefer Finish which validates completion

## Migration Checklist

### One-time: Add infrastructure

- [ ] Create `tests/support/tool_models.py` for test tool Pydantic input models
- [ ] Add `Step` Protocol to test helpers
- [ ] Add step dataclasses: `MakeCall`, `CheckThenCall`, `ExtractThenCall`, `Finish`, `AssistantMessage`
- [ ] Add `_StepRunner` class with proper typing: `Sequence[Step]`, `int` annotations
- [ ] Add `make_step_runner` pytest fixture to conftest.py (takes `responses_factory`)
- [ ] Fixture tracks all created runners and validates completion in teardown
- [ ] Ensure all type imports use `from __future__ import annotations`

### Per Test (convert to fixture usage)

**For complex multi-turn state machines:**
- [ ] Add `make_step_runner` to test function parameters
- [ ] Identify all turn numbers and if/elif blocks in agent's `_handle_turn`
- [ ] Map each if block to appropriate Step class:
  - Turn 1 (no check) → `MakeCall`
  - Check + call → `CheckThenCall`
  - Extract + use → `ExtractThenCall`
  - Final turn with validation → `Finish`
- [ ] Build typed `steps` list from turn sequence
- [ ] Replace class instantiation with `make_step_runner(steps=[...])`
- [ ] Delete entire subclass (including `__init__`, `_handle_turn`, `max_turns`, `agent_name`)

**For simple 1-2 step sequences:**
- [ ] Add `make_step_runner` to test function parameters
- [ ] Create Pydantic models in `tests/support/tool_models.py` if needed
- [ ] Map `FakeOpenAIModel([...])` to `make_step_runner(steps=[...])`
- [ ] Use `MakeCall` for tool calls, `AssistantMessage` for text returns
- [ ] Remove `FakeOpenAIModel` and `build_mcp_function` imports

**Both:**
- [ ] Remove manual completion assertions - fixture handles this automatically

## Example: Before & After

**Before (23 lines):**
```python
class POAgentState(AgentStateBase):
    def __init__(self, factory: ResponsesFactory):
        super().__init__(factory, agent_name="PO Agent", max_turns=5)

    def _handle_turn(self, req: ResponsesRequest) -> ResponsesResult:
        if self.turn == 1:
            return self.factory.make_tool_call(...)
        if self.turn == 2:
            assert_last_call(req, "docker_exec")
            return self.factory.make_tool_call(...)
        if self.turn == 3:
            out = assert_and_extract(req, "upsert_prompt", UpsertPromptOutput)
            return self.factory.make_tool_call(..., sha=out.prompt_sha256)
        if self.turn == 4:
            out = assert_and_extract(req, "run_critic", RunCriticOutput)
            return self.factory.make_tool_call(..., id=out.critique_id)
        if self.turn == 5:
            assert_last_call(req, "run_grader")
            return self.factory.make_assistant_message("Done")
        raise RuntimeError(f"Unexpected turn {self.turn}")
```

**After (9 lines):**
```python
po_agent = make_step_runner(steps=[
    MakeCall("docker", "exec", ExecInput(...)),
    CheckThenCall("docker_exec", "prompt_eval", "upsert_prompt", UpsertPromptInput(...)),
    ExtractThenCall("prompt_eval_upsert_prompt", UpsertPromptOutput,
                   lambda out: ("prompt_eval", "run_critic", CriticInput(..., sha=out.prompt_sha256))),
    ExtractThenCall("prompt_eval_run_critic", RunCriticOutput,
                   lambda out: ("prompt_eval", "run_grader", RunGraderInput(..., id=out.critique_id))),
    Finish("prompt_eval_run_grader"),
])
# Fixture automatically validates all 5 steps completed
```

**Savings:** 61% fewer lines, zero imperative logic, zero duplication, no inheritance, automatic completion checking
