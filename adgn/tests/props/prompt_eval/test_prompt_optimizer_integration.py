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

from hamcrest import assert_that, equal_to, has_length, has_properties, not_none
import pytest

from adgn.mcp._shared.naming import build_mcp_function
from adgn.openai_utils.model import OpenAIModelProto, ResponsesRequest, ResponsesResult
from adgn.props.critic.submit_server import (
    SUBMIT_PREFIX as CRITIC_SUBMIT_PREFIX,
    AddOccurrenceInput,
    CriticSubmitInput,
    UpsertIssueInput,
)
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import CriticRun, GraderRun, GradingDecision, TruePositive
from adgn.props.db.sync import sync_examples_to_db, sync_issues_to_db, sync_snapshots_to_db
from adgn.props.docker_env import DOCKER_MOUNT_PREFIX
from adgn.props.grader.grader import GraderSubmitServer
from adgn.props.grader.models import (
    CanonicalTPCoverage,
    GradeSubmitInput,
    IssueCoverageEntry,
    TPCoverageEntry,
    TruePositiveID,
)
from adgn.props.grader.submit_server import SUBMIT_PREFIX as GRADER_SUBMIT_PREFIX
from adgn.props.ids import InputIssueID, SnapshotSlug
from adgn.props.models.critic_scopes import ExplicitFileScope
from adgn.props.prompt_optimize.prompt_optimizer import (
    PromptEvalServer,
    PromptOptimizerCompositor,
    RunCriticOnExampleInput,
    RunCriticOutput,
    RunGraderInput,
    RunGraderOutput,
    UpsertPromptInput,
    UpsertPromptOutput,
    run_prompt_optimizer,
)
from adgn.props.prompt_optimize.target_metric import TargetMetric
from adgn.props.rationale import Rationale
from adgn.props.runs_context import RunsContext
from tests.support.responses import _StepRunner
from tests.support.steps import AssertDockerExecThenFinish, CheckThenCall, DockerExecCall, ExtractThenCall, MakeCall

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]

# Test specimen slugs used throughout this test
TEST_TRAIN_SLUG = SnapshotSlug("test-fixtures/test-trivial")
TEST_VALID_SLUG = SnapshotSlug("test-fixtures/test-validation")


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
    Uses test fixtures instead of production specimens.
    """

    # Sync test fixtures (matching synced_test_db pattern)
    specimens_dir = test_specimens_hydrator._base_path
    with get_session() as session:
        sync_snapshots_to_db(session, specimens_dir)
        sync_issues_to_db(session, specimens_dir)
        sync_examples_to_db(session, specimens_dir)

        # DEBUG: Check what was synced
        tps = session.query(TruePositive).filter_by(snapshot_slug=TEST_TRAIN_SLUG).all()
        print(f"\nDEBUG: Found {len(tps)} TPs for {TEST_TRAIN_SLUG}")
        for tp in tps:
            print(f"  TP: {tp.tp_id}")
            for occ in tp.occurrences:
                print(f"    occurrence: {occ.occurrence_id}, expect_caught_from: {occ.expect_caught_from}")

        examples = session.query(Example).all()
        print(f"\nDEBUG: Found {len(examples)} examples total")
        for ex in examples:
            print(
                f"  Example: slug={ex.snapshot_slug}, scope={ex.scope}, hash={ex.scope_hash[:16] if ex.scope_hash else 'None'}"
            )

    return test_db


@pytest.fixture
def po_agent_steps():
    """Declarative steps for PO agent - full prompt optimization workflow.

    Tests complete workflow:
    1. psql connectivity check (verifies database access)
    2. Train example evaluation (file-set with scope)
    3. Validation snapshot evaluation (whole-snapshot with AllFilesScope)
    4. Query validation results via get_validation_run_aggregates()
    """
    # Test files for the train example (matches test-issue.libsonnet expectCaughtFrom)
    test_files = ["subtract.py"]
    test_scope = ExplicitFileScope(files=test_files)

    # Compute scope_hash from scopes (use Example.from_scope to compute hash)
    test_scope_hash = Example.from_scope(TEST_TRAIN_SLUG, test_scope).scope_hash
    valid_all_files_scope_hash = Example.from_all_files(TEST_VALID_SLUG).scope_hash

    # Mutable container to capture state across steps (prompt_sha256 needed in Step 6)
    state: dict[str, str] = {}

    def make_train_critic_call(out: UpsertPromptOutput) -> tuple:
        """Capture prompt_sha256 and create train critic call."""
        state["prompt_sha256"] = out.prompt_sha256
        return (
            PromptOptimizerCompositor.PROMPT_EVAL_PREFIX,
            PromptEvalServer.RUN_CRITIC_ON_EXAMPLE_TOOL,
            RunCriticOnExampleInput(
                snapshot_slug=TEST_TRAIN_SLUG, scope_hash=test_scope_hash, prompt_sha256=out.prompt_sha256, max_turns=10
            ),
        )

    return [
        # Step 1: Verify psql connectivity (database access check)
        DockerExecCall(["psql", "-Atc", "SELECT 1"], timeout_ms=30000),
        # Step 2: Write prompt file
        DockerExecCall(
            ["sh", "-c", "echo 'Test critic system prompt for integration test.' > /workspace/prompt-v1.txt"],
            timeout_ms=30000,
        ),
        # Step 3: Upsert prompt to database
        CheckThenCall(
            expected_tool=build_mcp_function(DOCKER_MOUNT_PREFIX, "exec"),
            server=PromptOptimizerCompositor.PROMPT_EVAL_PREFIX,
            tool=PromptEvalServer.UPSERT_PROMPT_TOOL,
            args=UpsertPromptInput(file_path="/workspace/prompt-v1.txt"),
        ),
        # Step 4: Run critic on train example (file-set)
        # Captures prompt_sha256 in state for reuse in Step 6 (validation eval)
        ExtractThenCall(
            expected_tool=build_mcp_function(
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX, PromptEvalServer.UPSERT_PROMPT_TOOL
            ),
            output_type=UpsertPromptOutput,
            make_next=make_train_critic_call,
        ),
        # Step 5: Grade train critique
        ExtractThenCall(
            expected_tool=build_mcp_function(
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX, PromptEvalServer.RUN_CRITIC_ON_EXAMPLE_TOOL
            ),
            output_type=RunCriticOutput,
            make_next=lambda out: (
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX,
                PromptEvalServer.RUN_GRADER_TOOL,
                RunGraderInput(critic_run_id=out.critic_run_id, max_turns=10),
            ),
        ),
        # Step 6: Run critic on validation snapshot (whole-snapshot with AllFilesScope)
        # Uses captured prompt_sha256 from Step 4
        ExtractThenCall(
            expected_tool=build_mcp_function(
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX, PromptEvalServer.RUN_GRADER_TOOL
            ),
            output_type=RunGraderOutput,
            make_next=lambda out: (
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX,
                PromptEvalServer.RUN_CRITIC_ON_EXAMPLE_TOOL,
                RunCriticOnExampleInput(
                    snapshot_slug=TEST_VALID_SLUG,
                    scope_hash=valid_all_files_scope_hash,  # Whole-snapshot (required for validation)
                    prompt_sha256=state["prompt_sha256"],  # Reuse same prompt from Step 4
                    max_turns=10,
                ),
            ),
        ),
        # Step 7: Grade validation critique
        ExtractThenCall(
            expected_tool=build_mcp_function(
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX, PromptEvalServer.RUN_CRITIC_ON_EXAMPLE_TOOL
            ),
            output_type=RunCriticOutput,
            make_next=lambda out: (
                PromptOptimizerCompositor.PROMPT_EVAL_PREFIX,
                PromptEvalServer.RUN_GRADER_TOOL,
                RunGraderInput(critic_run_id=out.critic_run_id, max_turns=10),
            ),
        ),
        # Step 8: Query validation results via get_validation_run_aggregates()
        DockerExecCall(
            [
                "python",
                "-c",
                (
                    "from adgn.props.agent_helpers import setup_agent_database; "
                    "from adgn.props.db import get_session; "
                    "from sqlalchemy import text; "
                    "setup_agent_database(); "
                    "with get_session() as session: "
                    "    result = session.execute(text('SELECT * FROM get_validation_run_aggregates() ORDER BY grader_run_id DESC LIMIT 1')); "
                    "    row = result.fetchone(); "
                    "    print(f'validation_recall={row.recall if row else None}')"
                ),
            ],
            timeout_ms=30000,
        ),
        # Step 9: Verify validation recall query succeeded (final step)
        AssertDockerExecThenFinish(
            expected_output="validation_recall=0.8", message="Validation recall query succeeded - found recall=0.8"
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
    return [
        MakeCall(
            CRITIC_SUBMIT_PREFIX, "upsert_issue", UpsertIssueInput(issue_id="test-issue", description="Test issue")
        ),
        CheckThenCall(
            build_mcp_function(CRITIC_SUBMIT_PREFIX, "upsert_issue"),
            CRITIC_SUBMIT_PREFIX,
            "add_occurrence",
            AddOccurrenceInput(issue_id="test-issue", file="subtract.py", ranges=[[10, 15]]),
        ),
        CheckThenCall(
            build_mcp_function(CRITIC_SUBMIT_PREFIX, "add_occurrence"),
            CRITIC_SUBMIT_PREFIX,
            "submit",
            CriticSubmitInput(issues_count=1, summary="Test summary"),
        ),
    ]


@pytest.fixture
def grader_agent_steps():
    """Declarative steps for Grader agent - uses compositor/server constants.

    TODO: Same issue as critic_agent_steps - first step must be MakeCall to avoid
    pytest.fail() hangs from nested async contexts.
    """
    # Import here to get constants

    # Grader output using new coverage-based format with Pydantic models (minimal mock for integration test)
    grade_input = GradeSubmitInput(
        canonical_tp_coverage=[
            TPCoverageEntry(
                canonical_id=TruePositiveID("test-issue"),
                coverage=CanonicalTPCoverage(
                    covered_by=[IssueCoverageEntry(input_id=InputIssueID("test-issue"), credit=0.8)],
                    recall_credit=0.8,
                    rationale=Rationale("Test issue found with 80% coverage."),
                ),
            )
        ],
        canonical_fp_coverage=[],  # No false positives triggered
        novel_critique_issues=[],  # No novel issues
        summary=Rationale("Good coverage of canonical issues."),
    )
    return [MakeCall(GRADER_SUBMIT_PREFIX, GraderSubmitServer.SUBMIT_RESULT_TOOL_NAME, grade_input)]


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

    Workflow covered:
    1. psql connectivity check (database access verification)
    2. Train example evaluation (file-set with ExplicitFileScope)
    3. Validation snapshot evaluation (whole-snapshot with AllFilesScope)
    4. Query validation results via get_validation_run_aggregates()

    This test catches bugs like:
    - Naming collisions (run_critic tool vs run_critic function)
    - Tool name prefixing issues
    - Database schema problems
    - RLS policy issues (validation snapshot visibility)
    - Whole-snapshot vs file-set evaluation (AllFilesScope vs ExplicitFileScope)

    Set DUMP_REQUESTS env var to override dump directory (defaults to test tmp_path).
    Uses test-fixtures/test-trivial (train) and test-fixtures/test-validation (valid) specimens.
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
        target_metric=TargetMetric.WHOLE_REPO,
    )

    # Step runner validates all steps were executed

    # Verify train critique run
    train_critic_runs = get_critic_runs_for_slug(TEST_TRAIN_SLUG)
    assert_that(train_critic_runs, has_length(1), "Expected exactly one train critic run")
    train_critic_run = train_critic_runs[0]
    assert_that(train_critic_run, has_properties(model=equal_to("fake-model"), id=not_none()))

    # Verify validation critique run
    valid_critic_runs = get_critic_runs_for_slug(TEST_VALID_SLUG)
    assert_that(valid_critic_runs, has_length(1), "Expected exactly one validation critic run")
    valid_critic_run = valid_critic_runs[0]
    assert_that(valid_critic_run, has_properties(model=equal_to("fake-model"), id=not_none()))

    # Verify train grader run
    train_grader_runs = get_grader_runs_for_slug(TEST_TRAIN_SLUG)
    assert_that(train_grader_runs, has_length(1), "Expected exactly one train grader run")
    train_grader_run = train_grader_runs[0]
    assert_that(
        train_grader_run, has_properties(critic_run_id=equal_to(train_critic_run.id), model=equal_to("fake-model"))
    )
    # Verify grading decisions (check credit values)
    with get_session() as session:
        decisions = session.query(GradingDecision).filter_by(grader_run_id=train_grader_run.id).all()
        assert_that(decisions, has_length(1), "Expected exactly one grading decision")
        assert_that(decisions[0].credit, equal_to(0.8), "Expected credit=0.8 from mock grader")

    # Verify validation grader run
    valid_grader_runs = get_grader_runs_for_slug(TEST_VALID_SLUG)
    assert_that(valid_grader_runs, has_length(1), "Expected exactly one validation grader run")
    valid_grader_run = valid_grader_runs[0]
    assert_that(
        valid_grader_run, has_properties(critic_run_id=equal_to(valid_critic_run.id), model=equal_to("fake-model"))
    )
    # Verify grading decisions (check credit values)
    with get_session() as session:
        decisions = session.query(GradingDecision).filter_by(grader_run_id=valid_grader_run.id).all()
        assert_that(decisions, has_length(1), "Expected exactly one grading decision")
        assert_that(decisions[0].credit, equal_to(0.8), "Expected credit=0.8 from mock grader")


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
        target_metric=TargetMetric.WHOLE_REPO,
    )

    # Step runner validates that psql executed successfully and returned "1"
