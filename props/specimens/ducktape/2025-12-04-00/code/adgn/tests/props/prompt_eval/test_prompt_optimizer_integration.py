"""Full prompt optimizer workflow integration test.

Tests the complete workflow: PO agent → run_critic → critic agent → run_grader → grader agent
All three agents (PO, critic, grader) are driven by step runners with declarative sequences.
Verifies database records are created correctly and catches bugs like naming collisions.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import patch

from hamcrest import assert_that, equal_to, has_entry, has_length, has_properties, not_none
import pytest

from adgn.mcp.exec.models import ExecInput
from adgn.openai_utils.model import OpenAIModelProto, ResponsesRequest, ResponsesResult
from adgn.props.critic.critic import AddOccurrenceInput, SubmitInput, UpsertIssueInput
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, GraderRun, Snapshot
from adgn.props.grader.models import GradeSubmitInput
from adgn.props.ids import SnapshotSlug
from adgn.props.models.snapshot import LocalSource
from adgn.props.prompt_optimizer import (
    RunCriticOutput,
    RunGraderInput,
    UpsertPromptInput,
    UpsertPromptOutput,
    run_prompt_optimizer,
)
from adgn.props.runs_context import RunsContext
from tests.support.responses import _StepRunner
from tests.support.steps import CheckThenCall, ExtractThenCall, Finish, MakeCall

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]

# Test specimen slug used throughout this test
TEST_SPECIMEN_SLUG = "test-fixtures/test-trivial"


def get_critic_runs_for_slug(slug: str) -> list[CriticRun]:
    """Query all critic runs for a given snapshot slug."""
    with get_session() as session:
        runs = session.query(CriticRun).filter_by(snapshot_slug=slug).all()
        # Expire all objects to allow lazy-loading attributes after session closes
        session.expunge_all()
        return runs


def get_grader_runs_for_slug(slug: str) -> list[GraderRun]:
    """Query all grader runs for a given snapshot slug."""
    with get_session() as session:
        runs = session.query(GraderRun).filter_by(snapshot_slug=slug).all()
        # Expire all objects to allow lazy-loading attributes after session closes
        session.expunge_all()
        return runs


@pytest.fixture
def test_specimen(test_db):
    """Create test specimen record (uses test_db fixture from tests/props/conftest.py)."""
    with get_session() as session:
        specimen = Snapshot(slug=TEST_SPECIMEN_SLUG, split="train", source=LocalSource(vcs="local", root="."))
        session.merge(specimen)
        session.commit()


@pytest.fixture
def po_agent_steps():
    """Declarative steps for PO agent - prompt optimization workflow."""
    return [
        MakeCall(
            "docker",
            "exec",
            ExecInput(
                cmd=["sh", "-c", "echo 'Test critic system prompt for integration test.' > /workspace/prompt-v1.txt"],
                timeout_ms=30000,
            ),
        ),
        CheckThenCall(
            "docker_exec", "prompt_eval", "upsert_prompt", UpsertPromptInput(file_path="/workspace/prompt-v1.txt")
        ),
        ExtractThenCall(
            "prompt_eval_upsert_prompt",
            UpsertPromptOutput,
            lambda out: (
                "prompt_eval",
                "run_critic",
                CriticInput(
                    snapshot_slug=SnapshotSlug(TEST_SPECIMEN_SLUG), files="all", prompt_sha256=out.prompt_sha256
                ),
            ),
        ),
        ExtractThenCall(
            "prompt_eval_run_critic",
            RunCriticOutput,
            lambda out: ("prompt_eval", "run_grader", RunGraderInput(critique_id=out.critique_id)),
        ),
        Finish("prompt_eval_run_grader", message="Done"),
    ]


@pytest.fixture
def critic_agent_steps():
    """Declarative steps for Critic agent - reports issues."""
    return [
        MakeCall("critic_submit", "upsert_issue", UpsertIssueInput(tp_id="test-issue", description="Test issue")),
        CheckThenCall(
            "critic_submit_upsert_issue",
            "critic_submit",
            "add_occurrence",
            AddOccurrenceInput(tp_id="test-issue", file="subtract.py", ranges=[[10, 15]]),
        ),
        CheckThenCall("critic_submit_add_occurrence", "critic_submit", "submit", SubmitInput(issues_count=1)),
    ]


@pytest.fixture
def grader_agent_steps():
    """Declarative steps for Grader agent - evaluates critic output."""
    grade_input = {
        "canonical_tp_coverage": {
            "test-issue": {
                "covered_by": {"test-issue": 1.0},
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
    return [MakeCall("grader_submit", "submit_result", GradeSubmitInput.model_validate(grade_input))]


class WorkflowMock(OpenAIModelProto):
    """Smart mock that delegates to appropriate step runner based on tool context."""

    def __init__(
        self, po_runner: _StepRunner, critic_runner: _StepRunner, grader_runner: _StepRunner, dump_requests_to: Path
    ):
        self.po_runner = po_runner
        self.critic_runner = critic_runner
        self.grader_runner = grader_runner
        self.dump_requests_to = dump_requests_to

    @property
    def model(self) -> str:
        return "fake-model"

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        """Determine which agent from request context and delegate to appropriate runner."""
        # Dump request for debugging
        self._dump_request(req)

        # Determine agent type from available tools
        tool_names = {t.name for t in req.tools} if req.tools else set()

        if any("critic_submit" in name for name in tool_names):
            return await self.critic_runner.handle_request_async(req)
        if any("grader_submit" in name for name in tool_names):
            return await self.grader_runner.handle_request_async(req)
        return await self.po_runner.handle_request_async(req)

    def _dump_request(self, req: ResponsesRequest):
        """Dump request to file for debugging. Creates separate files per agent in subdirectories."""
        tool_names = {t.name for t in req.tools} if req.tools else set()

        if any("critic_submit" in name for name in tool_names):
            agent_type = "critic"
            turn_num = self.critic_runner.turn
        elif any("grader_submit" in name for name in tool_names):
            agent_type = "grader"
            turn_num = self.grader_runner.turn
        else:
            agent_type = "po"
            turn_num = self.po_runner.turn

        # Create agent-specific subdirectory
        agent_dir = self.dump_requests_to / agent_type
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Write full request to file named by turn number
        with (agent_dir / f"{turn_num}.json").open("w") as f:
            json.dump(req.model_dump(mode="json"), f, indent=2)


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_full_workflow_po_agent_critic_grader(
    test_specimen,
    tmp_path,
    make_step_runner,
    po_agent_steps,
    critic_agent_steps,
    grader_agent_steps,
    test_specimens_registry,
):
    """Full integration: run_prompt_optimizer() with real Docker, mocked LLM and specimens.

    Tests the complete CLI workflow: specimen hydration → Docker setup → compositor → agent → database writes.

    This test catches bugs like:
    - Naming collisions (run_critic tool vs run_critic function)
    - Tool name prefixing issues
    - Database schema problems
    - RLS policy issues
    - New workflow: docker_exec write_file → upsert_prompt → run_critic (with SHA256) → run_grader

    Set DUMP_REQUESTS env var to override dump directory (defaults to test tmp_path).
    Uses test-fixtures/test-trivial specimen from test fixtures registry.
    """
    # Create step runners for each agent
    po_runner = make_step_runner(steps=po_agent_steps)
    critic_runner = make_step_runner(steps=critic_agent_steps)
    grader_runner = make_step_runner(steps=grader_agent_steps)

    # Always dump requests; use DUMP_REQUESTS override or default to tmp_path
    dump_dir = Path(os.environ.get("DUMP_REQUESTS", str(tmp_path / "agent_requests")))
    mock = WorkflowMock(
        po_runner=po_runner, critic_runner=critic_runner, grader_runner=grader_runner, dump_requests_to=dump_dir
    )

    with patch("adgn.props.prompt_optimizer.build_client", return_value=mock):
        await run_prompt_optimizer(
            budget=1.0,
            ctx=RunsContext.from_pkg_dir(),
            registry=test_specimens_registry,
            out_dir=tmp_path,
            model="gpt-5-nano",
        )

    # make_step_runner fixture automatically validates all steps were executed for all three agents

    critic_runs = get_critic_runs_for_slug(TEST_SPECIMEN_SLUG)
    assert_that(critic_runs, has_length(1), "Expected exactly one critic run")
    critic_run = critic_runs[0]
    assert_that(critic_run, has_properties(model=equal_to("fake-model"), critique_id=not_none()))

    grader_runs = get_grader_runs_for_slug(TEST_SPECIMEN_SLUG)
    assert_that(grader_runs, has_length(1), "Expected exactly one grader run")
    grader_run = grader_runs[0]
    assert_that(
        grader_run,
        has_properties(
            critique_id=equal_to(critic_run.critique_id),
            model=equal_to("fake-model"),
            output=has_entry("grade", has_entry("recall", equal_to(0.8))),
        ),
    )
