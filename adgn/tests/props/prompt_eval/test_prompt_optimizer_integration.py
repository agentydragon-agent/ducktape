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

from hamcrest import assert_that, equal_to, has_length, has_properties, instance_of, not_none
import pytest

from adgn.mcp._shared.naming import build_mcp_function
from adgn.openai_utils.model import OpenAIModelProto, ResponsesRequest, ResponsesResult
from adgn.props.critic.critic import (
    AddOccurrenceInput,
    CriticCompositor,
    CriticSubmitServer,
    SubmitInput,
    UpsertIssueInput,
)
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, GraderRun
from adgn.props.db.snapshots import DBGraderSuccess
from adgn.props.docker_env import DOCKER_MOUNT_PREFIX
from adgn.props.files_hash import hash_file_set
from adgn.props.grader.grader import GraderCompositor, GraderSubmitServer
from adgn.props.grader.models import GradeSubmitInput
from adgn.props.ids import SnapshotSlug
from adgn.props.prompt_optimize.prompt_optimizer import (
    PromptEvalServer,
    PromptOptimizerCompositor,
    RunCriticOnExampleInput,
    RunCriticOutput,
    RunGraderInput,
    UpsertPromptInput,
    UpsertPromptOutput,
    run_prompt_optimizer,
)
from adgn.props.runs_context import RunsContext
from tests.support.responses import _StepRunner
from tests.support.steps import (
    AssertDockerExecThenFinish,
    CheckThenCall,
    DockerExecCall,
    ExtractThenCall,
    Finish,
    MakeCall,
)

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]

# Test specimen slug used throughout this test
TEST_SPECIMEN_SLUG = SnapshotSlug("test-fixtures/test-trivial")


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
def test_specimen(test_db, test_specimens_hydrator):
    """Sync test fixtures to database (snapshots, issues, examples).

    Examples are auto-generated from expect_caught_from in the issue file.
    Uses patch to point sync_all at test fixtures instead of production specimens.
    """
    from adgn.props.cli.cmd_db import sync_all

    # Patch get_specimens_base_path to return test fixtures path
    with patch("adgn.props.cli.cmd_db.get_specimens_base_path", return_value=test_specimens_hydrator._base_path):
        sync_all()


@pytest.fixture
def po_agent_steps():
    """Declarative steps for PO agent - prompt optimization workflow."""
    # Compute files_hash for the test example (matches test-issue.libsonnet expectCaughtFrom)
    test_files = ["subtract.py"]
    files_hash = hash_file_set(test_files)

    # Use shared constants

    return [
        DockerExecCall(
            ["sh", "-c", "echo 'Test critic system prompt for integration test.' > /workspace/prompt-v1.txt"],
            timeout_ms=30000,
        ),
        CheckThenCall(
            expected_tool=build_mcp_function(DOCKER_MOUNT_PREFIX, "exec"),
            server=PromptOptimizerCompositor.PROMPT_EVAL_PREFIX,
            tool=PromptEvalServer.UPSERT_PROMPT_TOOL,
            args=UpsertPromptInput(file_path="/workspace/prompt-v1.txt"),
        ),
        ExtractThenCall(
            expected_tool=build_mcp_function(
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX, PromptEvalServer.UPSERT_PROMPT_TOOL
            ),
            output_type=UpsertPromptOutput,
            make_next=lambda out: (
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX,
                PromptEvalServer.RUN_CRITIC_ON_EXAMPLE_TOOL,
                RunCriticOnExampleInput(
                    snapshot_slug=TEST_SPECIMEN_SLUG,
                    files_hash=files_hash,
                    prompt_sha256=out.prompt_sha256,
                    max_turns=10,
                ),
            ),
        ),
        ExtractThenCall(
            expected_tool=build_mcp_function(
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX, PromptEvalServer.RUN_CRITIC_ON_EXAMPLE_TOOL
            ),
            output_type=RunCriticOutput,
            make_next=lambda out: (
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX,
                PromptEvalServer.RUN_GRADER_TOOL,
                RunGraderInput(critique_id=out.critique_id, max_turns=10),
            ),
        ),
        Finish(
            expected_tool=build_mcp_function(
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX, PromptEvalServer.RUN_GRADER_TOOL
            ),
            message="Done",
        ),
    ]


@pytest.fixture
def critic_agent_steps():
    """Declarative steps for Critic agent - uses compositor/server constants.

    TODO: pytest.fail() from nested agent contexts (PO → critic → mock) doesn't propagate
    properly and causes hangs instead of fast-fails. This is why the first step MUST be
    MakeCall (no assertions) rather than CheckThenCall. The test framework can't catch
    exceptions raised deep in async agent execution chains.
    """
    # Import here to get constants

    prefix = CriticCompositor.SUBMIT_PREFIX

    return [
        MakeCall(
            prefix,
            CriticSubmitServer.UPSERT_ISSUE_TOOL_NAME,
            UpsertIssueInput(issue_id="test-issue", description="Test issue"),
        ),
        CheckThenCall(
            build_mcp_function(prefix, CriticSubmitServer.UPSERT_ISSUE_TOOL_NAME),
            prefix,
            CriticSubmitServer.ADD_OCCURRENCE_TOOL_NAME,
            AddOccurrenceInput(issue_id="test-issue", file="subtract.py", ranges=[[10, 15]]),
        ),
        CheckThenCall(
            build_mcp_function(prefix, CriticSubmitServer.ADD_OCCURRENCE_TOOL_NAME),
            prefix,
            CriticSubmitServer.SUBMIT_TOOL_NAME,
            SubmitInput(issues_count=1),
        ),
    ]


@pytest.fixture
def grader_agent_steps():
    """Declarative steps for Grader agent - uses compositor/server constants.

    TODO: Same issue as critic_agent_steps - first step must be MakeCall to avoid
    pytest.fail() hangs from nested async contexts.
    """
    # Import here to get constants

    grade_input = {
        "canonical_tp_coverage": [
            {
                "canonical_id": "test-issue",
                "coverage": {
                    "covered_by": [{"input_id": "test-issue", "credit": 1.0}],
                    "recall_credit": 1.0,
                    "rationale": "Test issue matches canonical TP.",
                },
            }
        ],
        "canonical_fp_coverage": [],
        "novel_critique_issues": [],
        "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
        "recall": 0.8,
        "summary": "Good coverage of canonical issues.",
    }
    return [
        MakeCall(
            GraderCompositor.SUBMIT_PREFIX,
            GraderSubmitServer.SUBMIT_RESULT_TOOL_NAME,
            GradeSubmitInput.model_validate(grade_input),
        )
    ]


class SimpleMockClient(OpenAIModelProto):
    """Simple mock client that delegates to a step runner and optionally dumps requests."""

    def __init__(self, runner: _StepRunner, agent_type: str, dump_dir: Path | None = None):
        self.runner = runner
        self.agent_type = agent_type
        self.dump_dir = dump_dir
        self.model = "fake-model"

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        """Delegate to runner and optionally dump request for debugging."""
        if self.dump_dir:
            self._dump_request(req)
        return await self.runner.handle_request_async(req)

    def _dump_request(self, req: ResponsesRequest):
        """Dump request to file for debugging."""
        assert self.dump_dir is not None
        agent_dir = self.dump_dir / self.agent_type
        agent_dir.mkdir(parents=True, exist_ok=True)
        with (agent_dir / f"{self.runner.turn}.json").open("w") as f:
            json.dump(req.model_dump(mode="json"), f, indent=2)


@pytest.mark.timeout(10)
@pytest.mark.requires_docker
async def test_full_workflow_po_agent_critic_grader(
    test_specimen,
    tmp_path,
    make_step_runner,
    po_agent_steps,
    critic_agent_steps,
    grader_agent_steps,
    test_specimens_hydrator,
    patch_prompt_optimizer_for_test_db,
    async_docker_client,
):
    """Full integration: prompt optimizer agent with compositor-based tool orchestration.

    Tests the complete workflow: PO agent → run_critic → critic agent → run_grader → grader agent.

    This test catches bugs like:
    - Naming collisions (run_critic tool vs run_critic function)
    - Tool name prefixing issues
    - Database schema problems
    - RLS policy issues
    - New workflow: docker_exec write_file → upsert_prompt → run_critic_on_example → run_grader

    Set DUMP_REQUESTS env var to override dump directory (defaults to test tmp_path).
    Uses test-fixtures/test-trivial specimen from test fixtures registry.
    """
    po_runner = make_step_runner(steps=po_agent_steps)
    critic_runner = make_step_runner(steps=critic_agent_steps)
    grader_runner = make_step_runner(steps=grader_agent_steps)

    dump_dir = Path(os.environ.get("DUMP_REQUESTS", str(tmp_path / "agent_requests")))

    # Create separate mock clients for each agent type
    optimizer_client = SimpleMockClient(po_runner, "po", dump_dir)
    critic_client = SimpleMockClient(critic_runner, "critic", dump_dir)
    grader_client = SimpleMockClient(grader_runner, "grader", dump_dir)

    # patch_prompt_optimizer_for_test_db fixture already applies the necessary patches
    await run_prompt_optimizer(
        budget=1.0,
        ctx=RunsContext.from_pkg_dir(),
        hydrator=test_specimens_hydrator,
        optimizer_client=optimizer_client,
        critic_client=critic_client,
        grader_client=grader_client,
        docker_client=async_docker_client,
        out_dir=tmp_path,
    )

    # Step runner validates all steps were executed

    critic_runs = get_critic_runs_for_slug(TEST_SPECIMEN_SLUG)
    assert_that(critic_runs, has_length(1), "Expected exactly one critic run")
    critic_run = critic_runs[0]
    assert_that(critic_run, has_properties(model=equal_to("fake-model"), critique_id=not_none()))

    grader_runs = get_grader_runs_for_slug(TEST_SPECIMEN_SLUG)
    assert_that(grader_runs, has_length(1), "Expected exactly one grader run")
    grader_run = grader_runs[0]
    assert_that(grader_run, has_properties(critique_id=equal_to(critic_run.critique_id), model=equal_to("fake-model")))
    assert_that(grader_run.output, instance_of(DBGraderSuccess))
    assert isinstance(grader_run.output, DBGraderSuccess)
    assert_that(grader_run.output.recall, equal_to(0.8))


@pytest.fixture
def patch_prompt_optimizer_for_test_db(test_db, test_specimens_hydrator):
    """Patch prompt optimizer to use test database and test specimens.

    Yields with patches active:
    - get_production_config() to return test database config
    - specimens_definitions_root() to return test fixtures path (patched where imported in hydration.py)
    """
    with (
        patch("adgn.props.prompt_optimize.prompt_optimizer.get_production_config", return_value=test_db),
        patch("adgn.props.hydration.specimens_definitions_root", return_value=test_specimens_hydrator._base_path),
    ):
        yield


@pytest.fixture
def psql_connectivity_steps():
    """Steps for PO agent testing psql connectivity via PG* env vars.

    This tests that the agent container can connect to postgres using the
    environment variables (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD)
    that are injected via properties_docker_spec.
    """
    return [
        DockerExecCall(["psql", "-Atc", "SELECT 1"], timeout_ms=30000),
        AssertDockerExecThenFinish(expected_output="1", message="psql connectivity verified"),
    ]


@pytest.mark.timeout(10)
@pytest.mark.requires_docker
async def test_po_agent_psql_connectivity(
    test_specimen,
    tmp_path,
    make_step_runner,
    psql_connectivity_steps,
    test_specimens_hydrator,
    patch_prompt_optimizer_for_test_db,
    async_docker_client,
):
    """Test that psql works from the agent container using PG* env vars.

    Verifies that:
    1. The container has access to psql
    2. PG* environment variables (PGHOST, PGPORT, etc.) are correctly injected
    3. Container can reach postgres via Docker network
    4. psql respects the PG* env vars and connects without explicit arguments
    """
    po_runner = make_step_runner(steps=psql_connectivity_steps)
    # Empty steps for critic/grader - they won't be invoked
    critic_runner = make_step_runner(steps=[])
    grader_runner = make_step_runner(steps=[])

    dump_dir = Path(os.environ.get("DUMP_REQUESTS", str(tmp_path / "agent_requests")))

    # Create separate mock clients for each agent type
    optimizer_client = SimpleMockClient(po_runner, "po", dump_dir)
    critic_client = SimpleMockClient(critic_runner, "critic", dump_dir)
    grader_client = SimpleMockClient(grader_runner, "grader", dump_dir)

    # patch_prompt_optimizer_for_test_db fixture already applies the necessary patches
    await run_prompt_optimizer(
        budget=1.0,
        ctx=RunsContext.from_pkg_dir(),
        hydrator=test_specimens_hydrator,
        optimizer_client=optimizer_client,
        critic_client=critic_client,
        grader_client=grader_client,
        docker_client=async_docker_client,
        out_dir=tmp_path,
    )

    # Step runner validates that psql executed successfully and returned "1"
