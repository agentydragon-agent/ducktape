"""Full prompt optimizer workflow integration test.

Tests the complete workflow: PO agent → run_critic → critic agent → run_grader → grader agent
All three agents (PO, critic, grader) are driven by a single OpenAI mock backend.
Verifies database records are created correctly and catches bugs like naming collisions.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TypeVar
from unittest.mock import patch

from hamcrest import assert_that, equal_to, has_length, not_none
from pydantic import BaseModel, TypeAdapter
import pytest

from adgn.mcp.exec.models import ExecInput
from adgn.openai_utils.model import (
    FunctionCallItem,
    FunctionCallOutputItem,
    OpenAIModelProto,
    ResponsesRequest,
    ResponsesResult,
)
from adgn.props.critic import AddOccurrenceInput, CriticInput, SubmitInput, UpsertIssueInput
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, GraderRun, Specimen
from adgn.props.grader import GradeSubmitInput
from adgn.props.prompt_optimizer import (
    RunCriticOutput,
    RunGraderInput,
    UpsertPromptInput,
    UpsertPromptOutput,
    run_prompt_optimizer,
)
from adgn.props.runs_context import RunsContext
from tests.support.responses import ResponsesFactory

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]

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
    if not item.output:
        raise ValueError(f"FunctionCallOutputItem has no output: {item}")

    # Parse the MCP result (CallToolResult)
    result_dict = json.loads(item.output)

    # Check for structured_content first (newer format)
    structured_content = result_dict.get("structured_content") or result_dict.get("structuredContent")

    # Fall back to content[0].text (older/default format)
    if structured_content is None:
        content = result_dict.get("content", [])
        if content and len(content) > 0:
            text_content = content[0].get("text", "")
            if text_content:
                try:
                    # Parse JSON from text field
                    structured_content = json.loads(text_content)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from text content: {text_content!r}")
                    logger.error(f"Full result_dict: {result_dict}")
                    raise ValueError(f"Invalid JSON in content[0].text: {e}") from e

    if structured_content is None:
        logger.error(f"No structured content found in result_dict: {result_dict}")
        raise ValueError(f"CallToolResult has no structured_content or parseable content: {result_dict}")

    # Parse structured content as the specific type
    return TypeAdapter(output_type).validate_python(structured_content)


def get_last_function_output(req: ResponsesRequest, output_type: type[T]) -> T:
    """Extract and parse structured content from last FunctionCallOutputItem in request input.

    Args:
        req: ResponsesRequest containing input items
        output_type: Pydantic model class to parse the structured content as

    Returns:
        Parsed and validated instance of output_type from the last FunctionCallOutputItem

    Raises:
        RuntimeError: If no FunctionCallOutputItem is found in input
    """
    if isinstance(req.input, str):
        raise RuntimeError("Cannot extract from string input")

    # Find last FunctionCallOutputItem with output
    for item in reversed(req.input):
        if isinstance(item, FunctionCallOutputItem) and item.output:
            return extract_structured_content(item, output_type)

    raise RuntimeError(f"No FunctionCallOutputItem found in request input for {output_type.__name__}")


def assert_last_call(req: ResponsesRequest, expected_tool: str):
    """Assert last FunctionCallItem matches expected tool."""
    if isinstance(req.input, str):
        logger.error("Full request dump:")
        logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
        pytest.fail(f"Expected FunctionCallItem for '{expected_tool}', got string input. See log for full request.")

    # Find last FunctionCallItem
    for item in reversed(req.input):
        if isinstance(item, FunctionCallItem):
            actual_name = item.name
            if expected_tool in actual_name:
                return  # Success

            logger.error("Full request dump:")
            logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
            pytest.fail(f"Expected last call to be '{expected_tool}', got '{actual_name}'. See log for full request.")

    logger.error("Full request dump:")
    logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
    pytest.fail(f"No FunctionCallItem found. Expected '{expected_tool}'. See log for full request.")


def extract_output(req: ResponsesRequest, output_type: type[T]) -> T:
    """Extract and validate output from last FunctionCallOutputItem."""
    try:
        return get_last_function_output(req, output_type)
    except Exception as e:
        logger.error("Full request dump:")
        logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
        pytest.fail(f"Failed to extract {output_type.__name__}: {e}. See log for full request.")


def assert_and_extract(req: ResponsesRequest, expected_tool: str, output_type: type[T]) -> T:
    """Assert expected tool and extract its output."""
    assert_last_call(req, expected_tool)
    return extract_output(req, output_type)


@pytest.fixture
def test_specimen(test_db):
    """Create test specimen record (uses test_db fixture from tests/props/conftest.py)."""
    with get_session() as session:
        specimen = Specimen(specimen_slug="test-fixtures/test-trivial", split="train", labeled_files=["subtract.py"])
        session.merge(specimen)
        session.commit()


class AgentStateBase:
    """Base class for agent state machines with shared validation logic."""

    def __init__(self, factory: ResponsesFactory, agent_name: str, max_turns: int):
        self.factory: ResponsesFactory = factory
        self.agent_name: str = agent_name
        self.max_turns: int = max_turns
        self.turn: int = 0

    def handle_request(self, req: ResponsesRequest) -> ResponsesResult:
        """Main entry point - increments turn and checks bounds."""
        self.turn += 1

        if self.turn > self.max_turns:
            logger.error(f"{self.agent_name} Turn {self.turn}: Full request dump:")
            logger.error(json.dumps(req.model_dump(mode="json"), indent=2))
            pytest.fail(
                f"{self.agent_name} Turn {self.turn}: Exceeded expected {self.max_turns} turns. "
                f"See log for full request."
            )

        return self._handle_turn(req)

    def _handle_turn(self, req: ResponsesRequest) -> ResponsesResult:
        """Subclass implements turn-by-turn logic."""
        raise NotImplementedError


class POAgentState(AgentStateBase):
    """State machine for PO agent - manages prompt optimization workflow."""

    factory: ResponsesFactory  # Explicit type annotation for mypy

    def __init__(self, factory: ResponsesFactory):
        super().__init__(factory, agent_name="PO Agent", max_turns=5)

    def _handle_turn(self, req: ResponsesRequest) -> ResponsesResult:
        if self.turn == 1:
            # Turn 1: Initial - emit docker exec to write file
            return self.factory.make_mcp_tool_call(
                "docker",
                "exec",
                ExecInput(
                    cmd=[
                        "sh",
                        "-c",
                        "echo 'Test critic system prompt for integration test.' > /workspace/prompt-v1.txt",
                    ],
                    timeout_ms=30000,  # 30 second timeout
                ),
            )

        if self.turn == 2:
            # Turn 2: Check docker exec completed - emit upsert_prompt
            assert_last_call(req, "docker_exec")
            return self.factory.make_tool_call(
                "prompt_eval_upsert_prompt", UpsertPromptInput(file_path="/workspace/prompt-v1.txt").model_dump()
            )

        if self.turn == 3:
            # Turn 3: Check upsert_prompt completed - emit run_critic with SHA256
            upsert_result = assert_and_extract(req, "prompt_eval_upsert_prompt", UpsertPromptOutput)

            return self.factory.make_tool_call(
                "prompt_eval_run_critic",
                CriticInput(
                    specimen_slug="test-fixtures/test-trivial", files="all", prompt_sha256=upsert_result.prompt_sha256
                ).model_dump(),
            )

        if self.turn == 4:
            # Turn 4: Check run_critic completed - emit run_grader with critique_id
            critic_result = assert_and_extract(req, "prompt_eval_run_critic", RunCriticOutput)

            return self.factory.make_tool_call(
                "prompt_eval_run_grader", RunGraderInput(critique_id=critic_result.critique_id).model_dump(mode="json")
            )

        if self.turn == 5:
            # Turn 5: Check run_grader completed - finish
            assert_last_call(req, "prompt_eval_run_grader")
            return self.factory.make_assistant_message("Done")

        raise RuntimeError(f"Unexpected turn {self.turn} for {self.agent_name}")


class CriticAgentState(AgentStateBase):
    """State machine for Critic agent - reports issues."""

    factory: ResponsesFactory  # Explicit type annotation for mypy

    def __init__(self, factory: ResponsesFactory):
        super().__init__(factory, agent_name="Critic Agent", max_turns=3)

    def _handle_turn(self, req: ResponsesRequest) -> ResponsesResult:
        if self.turn == 1:
            # Turn 1: Initial - emit upsert_issue
            return self.factory.make_mcp_tool_call(
                "critic_submit", "upsert_issue", UpsertIssueInput(issue_id="test-issue-001", description="Test issue")
            )

        if self.turn == 2:
            # Turn 2: Check upsert_issue completed - emit add_occurrence
            assert_last_call(req, "critic_submit_upsert_issue")
            return self.factory.make_mcp_tool_call(
                "critic_submit",
                "add_occurrence",
                AddOccurrenceInput(issue_id="test-issue-001", file="subtract.py", ranges=[[10, 20]]),
            )

        if self.turn == 3:
            # Turn 3: Check add_occurrence completed - emit submit
            assert_last_call(req, "critic_submit_add_occurrence")
            return self.factory.make_mcp_tool_call("critic_submit", "submit", SubmitInput(issues=1))

        raise RuntimeError(f"Unexpected turn {self.turn} for {self.agent_name}")


class GraderAgentState(AgentStateBase):
    """State machine for Grader agent - evaluates critic output."""

    factory: ResponsesFactory  # Explicit type annotation for mypy

    def __init__(self, factory: ResponsesFactory):
        super().__init__(factory, agent_name="Grader Agent", max_turns=1)

    def _handle_turn(self, req: ResponsesRequest) -> ResponsesResult:
        if self.turn == 1:
            # Turn 1: Initial - emit submit_result with grade
            grade_input = {
                "canonical_tp_coverage": {
                    "test-issue": {
                        "covered_by": {"test-issue-001": 1.0},
                        "recall_credit": 1.0,
                        "rationale": "Test issue matches canonical TP.",
                    }
                },
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
                "recall": 0.8,
                "summary": "Good coverage of canonical issues.",
                "per_file_recall": {"subtract.py": 0.8},
                "per_file_ratios": {"subtract.py": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0}},
            }

            return self.factory.make_mcp_tool_call(
                "grader_submit", "submit_result", GradeSubmitInput.model_validate(grade_input)
            )

        raise RuntimeError(f"Unexpected turn {self.turn} for {self.agent_name}")


class WorkflowMock(OpenAIModelProto):
    """Smart mock that delegates to appropriate agent state machine."""

    def __init__(self, dump_requests_to: Path | None = None):
        self.factory = ResponsesFactory("gpt-5-nano")
        self.dump_requests_to = dump_requests_to

        # Create state machines for each agent
        self.po_state = POAgentState(self.factory)
        self.critic_state = CriticAgentState(self.factory)
        self.grader_state = GraderAgentState(self.factory)

    @property
    def model(self) -> str:
        return "fake-model"

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        """Determine which agent from request context and delegate to appropriate state."""
        # Optionally dump request for debugging
        if self.dump_requests_to:
            self._dump_request(req)

        # Determine agent type from available tools
        tool_names = {t.name for t in req.tools} if req.tools else set()

        if any("critic_submit" in name for name in tool_names):
            return self.critic_state.handle_request(req)
        if any("grader_submit" in name for name in tool_names):
            return self.grader_state.handle_request(req)
        return self.po_state.handle_request(req)

    def _dump_request(self, req: ResponsesRequest):
        """Dump request to file for debugging."""
        assert self.dump_requests_to is not None
        tool_names = {t.name for t in req.tools} if req.tools else set()

        if any("critic_submit" in name for name in tool_names):
            agent_type = "critic"
            turn_num = self.critic_state.turn + 1
        elif any("grader_submit" in name for name in tool_names):
            agent_type = "grader"
            turn_num = self.grader_state.turn + 1
        else:
            agent_type = "po"
            turn_num = self.po_state.turn + 1

        dump_data = {"agent_type": agent_type, "turn": turn_num, "request": req.model_dump(mode="json")}

        with self.dump_requests_to.open("a") as f:
            f.write(json.dumps(dump_data, indent=2))
            f.write("\n" + "=" * 80 + "\n")


@pytest.mark.asyncio
async def test_full_workflow_po_agent_critic_grader(test_specimen, test_specimens_registry, tmp_path):
    """Full integration: run_prompt_optimizer() with real Docker, mocked LLM and specimens.

    Tests the complete CLI workflow: specimen hydration → Docker setup → compositor → agent → database writes.

    This test catches bugs like:
    - Naming collisions (run_critic tool vs run_critic function)
    - Tool name prefixing issues
    - Database schema problems
    - RLS policy issues
    - New workflow: docker_exec write_file → upsert_prompt → run_critic (with SHA256) → run_grader

    Set DUMP_REQUESTS env var to a file path to dump all agent requests.
    Uses test-fixtures/test-trivial specimen from test fixtures registry.
    """
    dump_path = os.environ.get("DUMP_REQUESTS")
    mock = WorkflowMock(dump_requests_to=Path(dump_path) if dump_path else None)

    with (
        patch(
            "adgn.props.specimens.registry.SpecimenRegistry.from_package_resources",
            return_value=test_specimens_registry,
        ),
        patch("adgn.props.prompt_optimizer.build_client", return_value=mock),
    ):
        await run_prompt_optimizer(budget=1.0, ctx=RunsContext.from_pkg_dir(), out_dir=tmp_path, model="gpt-5-nano")

    with get_session() as session:
        critic_runs = session.query(CriticRun).filter_by(specimen_slug="test-fixtures/test-trivial").all()
        assert_that(critic_runs, has_length(1))
        critic_run = critic_runs[0]
        assert_that(critic_run.model, equal_to("fake-model"))
        assert_that(critic_run.critique_id, not_none())

        grader_runs = session.query(GraderRun).filter_by(specimen_slug="test-fixtures/test-trivial").all()
        assert_that(grader_runs, has_length(1))
        grader_run = grader_runs[0]
        assert_that(grader_run.critique_id, equal_to(critic_run.critique_id))
        assert_that(grader_run.model, equal_to("fake-model"))
        assert_that(grader_run.output["grade"]["recall"], equal_to(0.8))
