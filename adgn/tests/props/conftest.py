"""Shared test fixtures for props tests."""

from collections.abc import AsyncGenerator, Callable, Generator
import hashlib
import inspect
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from adgn.openai_utils.model import AssistantMessageOut, OutputText, ResponsesResult
from adgn.props.cli.cmd_db import sync_all
from adgn.props.critic.models import CriticSubmitPayload, CriticSuccess
from adgn.props.db import dispose_db, get_session, init_db, recreate_database
from adgn.props.db.clustering_models import ClusteringRun
from adgn.props.db.config import DatabaseConfig, get_database_config
from adgn.props.db.examples import Example
from adgn.props.db.models import (
    CriticRun,
    CriticRunStatus,
    GraderRun,
    GraderRunStatus,
    GradingDecision,
    ReportedIssue,
    ReportedIssueOccurrence,
    Snapshot,
)
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.setup import ensure_database_exists
from adgn.props.db.snapshots import (
    DBCriticContextLengthExceeded,
    DBCriticMaxTurnsExceeded,
    DBCriticOutput,
    DBCriticSubmitPayload,
    DBCriticSuccess,
    DBGraderOutput,
    DBGraderSuccess,
    DBLocationAnchor,
    DBOccurrenceResult,
)
from adgn.props.grader.models import (
    GraderInput,
    GraderSuccess,
    InputIssueID,
    OccurrenceMatch,
    OccurrenceResult,
    TruePositiveID,
    UnknownIssue,
)
from adgn.props.grader.persistence import grader_success_to_db
from adgn.props.hydration import HydratedSnapshot, SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope
from adgn.props.models.true_positive import FalsePositiveOccurrence, LineRange, TruePositiveOccurrence
from adgn.props.rationale import Rationale
from adgn.props.runs_context import RunsContext
from tests.conftest import EMPTY_CANONICAL_ISSUES_SNAPSHOT
from tests.llm.support.openai_mock import FakeOpenAIModel


@pytest.fixture
def subtract_file_scope() -> ExplicitFileScope:
    """Scope for reviewing just subtract.py file."""
    return ExplicitFileScope(files=["subtract.py"])


@pytest.fixture
def all_files_scope() -> AllFilesScope:
    """Scope for reviewing all files in a snapshot."""
    return AllFilesScope()


# Scope fixtures for common test fixture files
@pytest.fixture
def add_py_scope() -> ExplicitFileScope:
    """Scope for reviewing just add.py file (test-trivial)."""
    return ExplicitFileScope(files=["add.py"])


@pytest.fixture
def multiply_py_scope() -> ExplicitFileScope:
    """Scope for reviewing just multiply.py file (test-trivial)."""
    return ExplicitFileScope(files=["multiply.py"])


@pytest.fixture
def divide_py_scope() -> ExplicitFileScope:
    """Scope for reviewing just divide.py file (test-trivial)."""
    return ExplicitFileScope(files=["divide.py"])


@pytest.fixture
def example_module_py_scope() -> ExplicitFileScope:
    """Scope for reviewing just example_module.py file (test-split-test)."""
    return ExplicitFileScope(files=["example_module.py"])


@pytest.fixture
def sample_subtract_py_scope() -> ExplicitFileScope:
    """Scope for reviewing just sample_subtract.py file (test-validation)."""
    return ExplicitFileScope(files=["sample_subtract.py"])


@pytest.fixture
def calculator_py_scope() -> ExplicitFileScope:
    """Scope for reviewing just calculator.py file (test-validation-2)."""
    return ExplicitFileScope(files=["calculator.py"])


@pytest.fixture(autouse=True)
def block_production_config_in_tests(monkeypatch: pytest.MonkeyPatch) -> Callable:
    """Prevent test functions from accidentally using production database.

    Tests should use the test_db fixture, which creates isolated test databases.
    Calling get_database_config() from test code is a bug - it returns production
    database credentials instead of the test-specific isolated database.

    This fixture blocks ALL calls to get_database_config() from test files.
    Production code (like database session management, Alembic offline mode) can
    still call it normally.
    """

    original = get_database_config

    def _block_from_tests(*args, **kwargs):
        # Check the immediate caller (frame 1)
        stack = inspect.stack()
        if len(stack) > 1:
            caller_frame = stack[1]
            caller_file = caller_frame.filename
            # If called from a test file, fail
            if "/tests/" in caller_file and caller_file.endswith(".py"):
                raise RuntimeError(
                    f"Tests must use test_db fixture, not get_database_config()!\n"
                    f"Called from: {caller_file}:{caller_frame.lineno}\n"
                    f"Fix: Use 'config = test_db' instead of 'get_database_config()'."
                )
        # Called from production code - allow it
        return original(*args, **kwargs)

    monkeypatch.setattr("adgn.props.db.config.get_database_config", _block_from_tests)

    # Return original for test_db fixture to use
    return original


@pytest.fixture
def test_example(synced_test_fixtures: DatabaseConfig) -> Example:
    """Get a real example from synced test fixtures for testing.

    Returns the first available example from the test fixtures database.
    Uses synced_test_fixtures to ensure examples are loaded.
    """
    with get_session() as session:
        example = session.query(Example).first()
        if not example:
            raise RuntimeError("No examples found in synced test fixtures database")
        # Detach from session so it can be used outside the context
        session.expunge(example)
        return example


def make_grader_output(
    tp_count: int = 1, summary: str = "Test grader output", found_credit: float = 0.0, unknowns: list[str] | None = None
) -> DBGraderOutput:
    """Build test grader output with per-occurrence results.

    Args:
        tp_count: Number of test occurrences to create (default: 1)
        summary: Summary text (default: "Test grader output")
        found_credit: Credit for each occurrence (0.0 = not found, 1.0 = fully found). Default: 0.0
        unknowns: Optional list of unknown issue IDs (unlabeled issues found by critic)

    Returns:
        DBGraderSuccess with specified parameters (or DBGraderOutput for unknowns)

    Example:
        # Create output with 80% recall across all occurrences
        output = make_grader_output(tp_count=5, found_credit=0.8)

        # Create output with unknowns (unlabeled issues)
        output = make_grader_output(tp_count=2, unknowns=["unknown-001", "unknown-002"])
    """
    occurrence_results = [
        OccurrenceResult(
            tp_id=TruePositiveID(f"tp-{i:03d}"),
            occurrence_id=f"occ-{i:03d}",
            found_credit=found_credit,
            matched_by=[OccurrenceMatch(input_id=InputIssueID(f"issue-{i:03d}"), credit=found_credit)]
            if found_credit > 0.0
            else [],
            rationale=Rationale(
                "Test occurrence - not found" if found_credit == 0.0 else f"Test occurrence (credit={found_credit})"
            ),
        )
        for i in range(1, tp_count + 1)
    ]

    grader_success = GraderSuccess(
        occurrence_results=occurrence_results,
        summary=Rationale(summary),
        unknowns=[UnknownIssue(input_id=InputIssueID(u), rationale=Rationale(f"Unknown issue: {u}")) for u in unknowns]
        if unknowns
        else [],
    )
    return grader_success_to_db(grader_success)


def make_critic_success(notes_md: str = "") -> DBCriticOutput:
    """Build successful critic output for test storage.

    Uses actual Pydantic DB models to ensure test data matches the schema.

    Note: Issues are now stored in the reported_issues table and accessed via
    critic_run.reported_issues ORM relationship, not in the payload.

    Args:
        notes_md: Notes in markdown (default: empty string, not None)

    Returns:
        DBCriticSuccess with the provided payload
    """
    return DBCriticSuccess(result=DBCriticSubmitPayload(notes_md=notes_md))


def make_critic_max_turns_exceeded(max_turns: int = 10) -> DBCriticOutput:
    """Build max_turns_exceeded critic output for test storage.

    Args:
        max_turns: Maximum turns that were allowed

    Returns:
        DBCriticMaxTurnsExceeded with the provided max_turns
    """
    return DBCriticMaxTurnsExceeded(max_turns=max_turns)


def make_critic_context_length_exceeded(error_message: str = "Context length exceeded") -> DBCriticOutput:
    """Build context_length_exceeded critic output for test storage.

    Args:
        error_message: Error message from the API

    Returns:
        DBCriticContextLengthExceeded with the provided error message
    """
    return DBCriticContextLengthExceeded(error_message=error_message)


def make_critique_payload(notes_md: str = "") -> DBCriticSubmitPayload:
    """Build critique payload for test storage.

    Note: Issues are now stored in the reported_issues table and accessed via
    critic_run.reported_issues ORM relationship, not in the payload.

    Args:
        notes_md: Notes in markdown (empty string by default)

    Returns:
        DBCriticSubmitPayload with the provided data
    """
    return DBCriticSubmitPayload(notes_md=notes_md)


# ============================================================================
# Test Fixture Builders (Pydantic models, not dicts!)
# ============================================================================


def make_tp_occurrence(
    occurrence_id: str = "occ-1",
    files: dict[Path, list[LineRange] | None] | None = None,
    expect_caught_from: set[frozenset[Path]] | None = None,
    note: str | None = None,
) -> TruePositiveOccurrence:
    """Build TruePositiveOccurrence with proper Pydantic types.

    Args:
        occurrence_id: Unique ID within the TP (default: "occ-1")
        files: File paths with optional line ranges
            - None (default): Single file Path("test.py") with no ranges
            - {Path("file.py"): None}: File with no line ranges
            - {Path("file.py"): [LineRange(...)]}: File with line ranges
        expect_caught_from: Minimal file sets for detection
            - None (default): Single trigger set containing first file
            - {frozenset([Path("file.py")])}: Set of frozensets of Paths
        note: Occurrence-specific note (optional)

    Returns:
        TruePositiveOccurrence with validated Pydantic types

    Examples:
        # Simple file, no line range (most common):
        make_tp_occurrence(files={Path("test.py"): None})

        # File with line range:
        make_tp_occurrence(
            files={Path("server.py"): [LineRange(start_line=10, end_line=20)]}
        )

        # Multiple trigger sets (OR logic):
        make_tp_occurrence(
            expect_caught_from={frozenset([Path("file1.py")]), frozenset([Path("file2.py")])}
        )

        # Trigger set requiring multiple files (AND logic):
        make_tp_occurrence(
            expect_caught_from={frozenset([Path("client.py"), Path("utils.py")])}
        )
    """
    # Default: single file with no ranges
    if files is None:
        files = {Path("test.py"): None}

    # Default: single trigger set containing first file
    if expect_caught_from is None:
        first_file = next(iter(files.keys()))
        expect_caught_from = {frozenset([first_file])}

    return TruePositiveOccurrence(
        occurrence_id=occurrence_id, files=files, note=note, expect_caught_from=expect_caught_from
    )


def make_fp_occurrence(
    occurrence_id: str = "occ-1",
    files: dict[Path, list[LineRange] | None] | None = None,
    relevant_files: set[Path] | None = None,
    note: str | None = None,
) -> FalsePositiveOccurrence:
    """Build FalsePositiveOccurrence with proper Pydantic types.

    Args:
        occurrence_id: Unique ID within the FP (default: "occ-1")
        files: File paths with optional line ranges (same format as make_tp_occurrence)
        relevant_files: Files that make this FP relevant
            - None (default): First file from files dict
            - {Path("file.py")}: Set of Paths
        note: Occurrence-specific note (optional)

    Returns:
        FalsePositiveOccurrence with validated Pydantic types

    Examples:
        # Simple FP:
        make_fp_occurrence(
            files={Path("helper.py"): None},
            relevant_files={Path("helper.py")}
        )
    """
    # Default: single file with no ranges
    if files is None:
        files = {Path("test.py"): None}

    # Default: first file from files dict
    if relevant_files is None:
        first_file = next(iter(files.keys()))
        relevant_files = {first_file}

    return FalsePositiveOccurrence(occurrence_id=occurrence_id, files=files, note=note, relevant_files=relevant_files)


# ============================================================================
# TruePositive / FalsePositive Builders
# ============================================================================


# ============================================================================
# Other Model Builders
# ============================================================================


# make_critique is DEPRECATED - Critique table has been eliminated
# Use make_critic_run instead to create CriticRun records


def make_clustering_run(snapshot_slug: SnapshotSlug, status: str = "in_progress", transcript_id: str | None = None):
    """Build ClusteringRun with defaults.

    Args:
        snapshot_slug: Snapshot this run analyzes (must be SnapshotSlug)
        status: Run status (default: "in_progress")
        transcript_id: Optional transcript ID

    Returns:
        ClusteringRun ORM model (not yet added to session)

    Examples:
        # Basic run:
        make_clustering_run(SnapshotSlug("test/spec-a"))

        # With custom status:
        make_clustering_run(SnapshotSlug("test/spec-b"), status="completed")
    """
    return ClusteringRun(snapshot_slug=snapshot_slug, status=status, transcript_id=transcript_id)


def get_example(session: Session, snapshot_slug: SnapshotSlug, scope: AllFilesScope | ExplicitFileScope) -> Example:
    """Get an existing Example from the database.

    For git fixture examples that should already exist (synced via fixtures).
    Raises an error if the example doesn't exist.

    Args:
        session: Active SQLAlchemy session
        snapshot_slug: Snapshot slug (SnapshotSlug type)
        scope: Scope for the example (AllFilesScope or ExplicitFileScope)

    Returns:
        Example: The existing example

    Raises:
        ValueError: If the example doesn't exist
    """
    example = Example.from_scope(snapshot_slug, scope)

    existing = (
        session.query(Example).filter_by(snapshot_slug=example.snapshot_slug, scope_hash=example.scope_hash).first()
    )

    if not existing:
        raise ValueError(
            f"Example not found for snapshot={snapshot_slug}, scope_hash={example.scope_hash}. "
            "Git fixtures may not be synced."
        )

    return existing


def get_or_create_example(
    session: Session, snapshot_slug: SnapshotSlug, scope: AllFilesScope | ExplicitFileScope
) -> Example:
    """Get or create an Example in the database.

    For test-specific examples that may not exist yet.
    Uses get-or-create pattern to avoid foreign key violations.

    Args:
        session: Active SQLAlchemy session
        snapshot_slug: Snapshot slug (SnapshotSlug type)
        scope: Scope for the example (AllFilesScope or ExplicitFileScope)

    Returns:
        Example: Either the existing example or newly created one
    """
    example = Example.from_scope(snapshot_slug, scope)

    # Get or create the example
    existing = (
        session.query(Example).filter_by(snapshot_slug=example.snapshot_slug, scope_hash=example.scope_hash).first()
    )

    if existing:
        return existing

    session.add(example)
    session.flush()
    return example


def make_critic_run(
    *,  # Force keyword arguments
    example: Example,  # Required, not optional
    prompt_sha256: str,  # Required
    model: str = "test-model",
    status: CriticRunStatus = CriticRunStatus.COMPLETED,
    completion_summary: str | None = None,
    transcript_id: UUID | None = None,
) -> CriticRun:
    """Build CriticRun from Example (preferred pattern).

    Derives snapshot_slug, scope, scope_hash from example automatically.

    Args:
        example: Example to derive snapshot_slug, scope_hash, and scope from (required)
        prompt_sha256: Hash of the prompt used (required)
        model: Model name (default: "test-model")
        status: Run status (default: COMPLETED)
        completion_summary: Markdown summary (auto-provided for COMPLETED status if None)
        transcript_id: Optional transcript ID (defaults to uuid4())

    Returns:
        CriticRun ORM model (not yet added to session)

    Examples:
        # Basic usage (with test_prompt_sha fixture):
        make_critic_run(example=my_example, prompt_sha256=test_prompt_sha)

        # With specific status:
        make_critic_run(example=my_example, prompt_sha256=test_prompt_sha, status=CriticRunStatus.MAX_TURNS_EXCEEDED)
    """
    # Derive fields from example
    snapshot_slug = example.snapshot_slug
    scope_hash = example.scope_hash

    if transcript_id is None:
        transcript_id = uuid4()

    # Auto-provide completion_summary for COMPLETED status (required by CHECK constraint)
    if completion_summary is None and status == CriticRunStatus.COMPLETED:
        completion_summary = "Test completion summary"

    return CriticRun(
        transcript_id=transcript_id,
        prompt_sha256=prompt_sha256,
        snapshot_slug=snapshot_slug,
        model=model,
        scope_hash=scope_hash,
        status=status,
        completion_summary=completion_summary,
    )


def make_grader_run(
    *,  # Force keyword arguments
    critic_run: CriticRun,  # Required
    canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
    model: str = "test-model",
    status: GraderRunStatus = GraderRunStatus.COMPLETED,
    transcript_id: UUID | None = None,
) -> GraderRun:
    """Build GraderRun from CriticRun (derives snapshot_slug and critic_run_id).

    Args:
        critic_run: Critic run being evaluated (derives snapshot_slug and critic_run_id)
        canonical_issues_snapshot: Snapshot of TPs+FPs used (default: EMPTY_CANONICAL_ISSUES_SNAPSHOT)
        model: Model name (default: "test-model")
        status: Run status (default: COMPLETED)
        transcript_id: Optional transcript ID (defaults to uuid4())

    Returns:
        GraderRun ORM model (not yet added to session)

    Examples:
        # Minimal usage (with critic_run):
        make_grader_run(critic_run=my_critic_run)

        # With specific status:
        make_grader_run(critic_run=my_critic_run, status=GraderRunStatus.MAX_TURNS_EXCEEDED)

        # With custom canonical issues:
        make_grader_run(critic_run=my_critic_run, canonical_issues_snapshot=my_snapshot)
    """
    # Derive from critic_run
    snapshot_slug = critic_run.snapshot_slug
    critic_run_id = critic_run.id

    if transcript_id is None:
        transcript_id = uuid4()

    return GraderRun(
        transcript_id=transcript_id,
        snapshot_slug=snapshot_slug,
        model=model,
        critic_run_id=critic_run_id,
        canonical_issues_snapshot=canonical_issues_snapshot,
        status=status,
    )


def extract_input_issue_ids(grader_output: DBGraderSuccess) -> list[str]:
    """Extract unique input issue IDs from grader output.

    Pure function for functional composition.

    Args:
        grader_output: Successful grader output with occurrence results

    Returns:
        Sorted list of unique input issue IDs
    """
    issue_ids = set()
    for occ_result in grader_output.occurrence_results:
        for match in occ_result.matched_by:
            issue_ids.add(str(match.input_id))
    return sorted(issue_ids)


def make_reported_issues(*, critic_run_id: UUID, issue_ids: list[str], session: Session) -> list[ReportedIssue]:
    """Create ReportedIssue and ReportedIssueOccurrence rows for a critic run.

    Deterministic factory - always creates fresh issues, no conditional logic.
    Call once per critic run with all issue IDs upfront.

    Args:
        critic_run_id: The critic run these issues belong to
        issue_ids: List of issue IDs to create (e.g., ["input-1", "input-2"])
        session: Database session

    Returns:
        List of created ReportedIssue objects
    """
    issues = []
    for issue_id in issue_ids:
        issue = ReportedIssue(critic_run_id=critic_run_id, issue_id=issue_id, rationale=f"Test issue {issue_id}")
        session.add(issue)
        session.flush()

        occurrence = ReportedIssueOccurrence(
            critic_run_id=critic_run_id,
            reported_issue_id=issue_id,
            locations=[DBLocationAnchor(file="test.py", start_line=1, end_line=1)],
        )
        session.add(occurrence)
        issues.append(issue)

    session.flush()
    return issues


def populate_grading_decisions(
    *, grader_run: GraderRun, occurrence_results: list[OccurrenceResult] | list[DBOccurrenceResult], session: Session
) -> None:
    """Create GradingDecision rows from occurrence results.

    Deterministic factory - creates one decision per match in occurrence results.
    No conditional logic, no side effects beyond session writes.

    Precondition: ReportedIssue rows must already exist for all input_issue_ids
    referenced in occurrence_results.

    Args:
        grader_run: GraderRun to associate decisions with
        occurrence_results: List of OccurrenceResult (MCP) or DBOccurrenceResult (DB persistence)
        session: Database session (uses provided session, not get_session())

    Raises:
        IntegrityError: If referenced input_issue_id doesn't exist (CHECK constraint)
    """
    # Create one GradingDecision per match in each occurrence result
    for occ_result in occurrence_results:
        for match in occ_result.matched_by:
            decision = GradingDecision(
                grader_run_id=grader_run.id,
                input_issue_id=str(match.input_id),
                target_tp_id=str(occ_result.tp_id),
                target_tp_occurrence_id=occ_result.occurrence_id,
                target_fp_id=None,
                target_fp_occurrence_id=None,
                credit=match.credit,
                rationale=str(occ_result.rationale),
            )
            session.add(decision)


def make_critic_and_grader_run(
    *, example: Example, prompt_sha256: str, grader_output: DBGraderOutput, session: Session
) -> tuple[CriticRun, GraderRun]:
    """One-stop helper: Creates complete critic+grader run with normalized tables.

    Convenience factory for tests that need both critic and grader data.
    Functional composition: extracts issue IDs from output, creates all data deterministically.

    Creates:
    - CriticRun with COMPLETED status
    - ReportedIssue rows (derived from grader_output)
    - ReportedIssueOccurrence rows (placeholder locations)
    - GraderRun with provided output
    - GradingDecision rows from grader output

    Args:
        example: Example being evaluated
        prompt_sha256: Critic prompt hash
        grader_output: Grader output (must be DBGraderSuccess for issue extraction)
        session: Database session

    Returns:
        (critic_run, grader_run) tuple
    """
    # Create critic run
    critic_run = make_critic_run(example=example, prompt_sha256=prompt_sha256, status=CriticRunStatus.COMPLETED)
    session.add(critic_run)
    session.flush()

    # Extract issue IDs from grader output (functional)
    if isinstance(grader_output, DBGraderSuccess):
        issue_ids = extract_input_issue_ids(grader_output)
        # Create reported issues (deterministic)
        make_reported_issues(critic_run_id=critic_run.id, issue_ids=issue_ids, session=session)

    # Derive grader status from output type
    grader_status = (
        GraderRunStatus.COMPLETED if isinstance(grader_output, DBGraderSuccess) else GraderRunStatus.MAX_TURNS_EXCEEDED
    )

    # Create grader run
    grader_run = GraderRun(
        transcript_id=uuid4(),
        snapshot_slug=example.snapshot_slug,
        critic_run_id=critic_run.id,
        model="test-grader",
        status=grader_status,
        canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
    )
    session.add(grader_run)
    session.flush()

    # Populate grading decisions (deterministic)
    if isinstance(grader_output, DBGraderSuccess):
        occurrence_results = grader_output.occurrence_results
        populate_grading_decisions(grader_run=grader_run, occurrence_results=occurrence_results, session=session)

    return critic_run, grader_run


def make_grader_run_with_decisions(
    *,  # Force keyword arguments
    critic_run: CriticRun,
    session: Session,
    canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
    model: str = "test-model",
    status: GraderRunStatus = GraderRunStatus.COMPLETED,
    occurrence_results: list[OccurrenceResult] | list[DBOccurrenceResult] | None = None,
    transcript_id: UUID | None = None,
) -> GraderRun:
    """Build GraderRun and populate grading_decisions table (one-step helper).

    Combines make_grader_run() + session.add/flush + populate_grading_decisions()
    to reduce boilerplate in tests that need normalized table data.

    DEPRECATED: This helper is rarely used. Prefer explicit test setup with
    make_reported_issues() + make_grader_run() + populate_grading_decisions().

    Args:
        critic_run: Critic run being evaluated (derives snapshot_slug and critic_run_id)
        session: Database session (required for decisions and flush)
        canonical_issues_snapshot: Snapshot of TPs+FPs used (default: EMPTY_CANONICAL_ISSUES_SNAPSHOT)
        model: Model name (default: "test-model")
        status: Run status (default: COMPLETED)
        occurrence_results: Occurrence results for populating decisions (optional)
        transcript_id: Optional transcript ID (defaults to uuid4())

    Returns:
        GraderRun ORM model (added to session, flushed, with grading_decisions populated)
    """
    grader_run = make_grader_run(
        critic_run=critic_run,
        canonical_issues_snapshot=canonical_issues_snapshot,
        model=model,
        status=status,
        transcript_id=transcript_id,
    )
    session.add(grader_run)
    session.flush()

    # Populate grading decisions if occurrence_results provided
    if occurrence_results:
        # Extract issue IDs and create reported issues first
        issue_ids = [str(match.input_id) for occ in occurrence_results for match in occ.matched_by]
        make_reported_issues(critic_run_id=critic_run.id, issue_ids=issue_ids, session=session)

        # Populate grading decisions from occurrence_results
        populate_grading_decisions(grader_run=grader_run, occurrence_results=occurrence_results, session=session)

    return grader_run


@pytest.fixture
def test_prompt_sha() -> str:
    """Create and return a test prompt hash (upserts to DB once)."""
    return hash_and_upsert_prompt("test prompt for database tests")


@pytest.fixture
def rationale_model() -> type[BaseModel]:
    """Fixture providing a Pydantic model with Rationale field."""

    class Model(BaseModel):
        rationale: Rationale

    return Model


# === Snapshot Hydrator Fixtures (DI Pattern) ===
# Two explicit hydrators:
# 1. production_specimens_hydrator - for real specimens (src/adgn/props/specimens/)
# 2. test_specimens_hydrator - for test fixtures (tests/props/fixtures/specimens/)


@pytest.fixture
def production_specimens_hydrator() -> SnapshotHydrator:
    """Production specimens hydrator from ADGN_PROPS_SPECIMENS_ROOT environment variable.

    Uses specimens from the external specimens repository.
    """
    return SnapshotHydrator.from_env()


@pytest.fixture
def test_specimens_base() -> Path:
    """Base directory for test-only fixture specimens.

    Returns path to tests/props/fixtures/specimens/ which contains
    minimal specimens for testing specific scenarios.
    """
    return Path(__file__).parent / "fixtures" / "specimens"


@pytest.fixture
def test_specimens_hydrator(test_specimens_base: Path) -> SnapshotHydrator:
    """Test fixtures specimens hydrator (DI pattern - no monkeypatching).

    Uses test fixtures from tests/props/fixtures/specimens/ which contains
    minimal test-only specimens like test-trivial.
    """
    return SnapshotHydrator(test_specimens_base)


@pytest_asyncio.fixture
async def loaded_specimen(
    production_specimens_hydrator: SnapshotHydrator, test_db: DatabaseConfig
) -> AsyncGenerator[HydratedSnapshot, None]:
    """Load a real specimen using hydrator.

    Yields HydratedSnapshot object (content_root + all_discovered_files).
    Issues must be loaded separately from database via ORM.

    Uses ducktape/2025-11-22-02 as the canonical test specimen.
    Depends on test_db to ensure database is initialized before hydration.
    """
    async with production_specimens_hydrator.hydrate(SnapshotSlug("ducktape/2025-11-22-02")) as hydrated:
        yield hydrated


@pytest_asyncio.fixture
async def test_trivial_specimen(
    test_specimens_hydrator: SnapshotHydrator, test_snapshot: SnapshotSlug
) -> AsyncGenerator[HydratedSnapshot, None]:
    """Load test-trivial fixture specimen (clean Python code, zero issues).

    Test-only specimen for validating zero-issues case.
    Lives in tests/props/fixtures/specimens/test-fixtures/test-trivial/.
    Uses DI - no monkeypatching needed.
    Depends on test_snapshot to ensure database record exists before hydration.
    """
    async with test_specimens_hydrator.hydrate(test_snapshot) as hydrated:
        yield hydrated


# =============================================================================
# Run managers fixtures
# =============================================================================


@pytest.fixture
def mock_snapshot_slug() -> SnapshotSlug:
    """Shared test snapshot slug."""
    return SnapshotSlug("ducktape/2025-11-26-00")


@pytest.fixture
def mock_prompt_sha256() -> str:
    """Mock SHA-256 hash for test prompts."""
    return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 of empty string


@pytest.fixture
def sample_critic_success() -> CriticSuccess:
    """Sample CriticSuccess with empty issues list."""
    return CriticSuccess(result=CriticSubmitPayload(issues=[], notes_md=None))


@pytest.fixture
def sample_grader_input() -> GraderInput:
    """Sample GraderInput with critic run ID (snapshot derived from critic run in database)."""
    return GraderInput(critic_run_id=uuid4())


@pytest.fixture
def runs_context(tmp_path: Path) -> RunsContext:
    """RunsContext using pytest tmp_path fixture.

    Available to props tests for creating temporary run directories.
    """
    return RunsContext(tmp_path)


@pytest.fixture
def mock_openai_client() -> FakeOpenAIModel:
    """Mock OpenAI client that returns empty assistant messages.

    For tests that need specific responses, create a custom FakeOpenAIModel
    with the desired response sequence.
    """
    # Single generic success response
    result = ResponsesResult(
        id="resp_test",
        usage=None,
        output=[AssistantMessageOut(parts=[OutputText(text="Task completed successfully.")])],
    )
    return FakeOpenAIModel([result])


@pytest.fixture
def make_openai_client() -> Callable[[list[ResponsesResult]], FakeOpenAIModel]:
    """Factory fixture for creating mock OpenAI clients from response sequences.

    Usage:
        responses = [factory.make(...), factory.make(...)]
        client = make_openai_client(responses)

    This is a props-specific alias for the pattern used in agent tests (make_fake_openai).
    """

    def _factory(responses: list[ResponsesResult]) -> FakeOpenAIModel:
        return FakeOpenAIModel(responses)

    return _factory


def _sanitize_test_id(test_id: str, max_length: int = 63) -> str:
    """Sanitize pytest node ID for use in PostgreSQL database name.

    Args:
        test_id: pytest node ID (e.g., 'tests/props/test_db.py::test_sync')
        max_length: Maximum length for PostgreSQL identifier (default 63)

    Returns:
        Sanitized database name safe for PostgreSQL
    """
    # Keep only alphanumeric and underscore; replace other chars with underscore
    sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in test_id)
    # Collapse consecutive underscores
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    # Trim leading/trailing underscores
    sanitized = sanitized.strip("_")
    # Ensure it fits PostgreSQL's 63-character limit (including 'props_test_' prefix)
    # Reserve space for the prefix that will be added later
    prefix = "props_test_"
    available_length = max_length - len(prefix)
    if len(sanitized) > available_length:
        # Keep prefix and add hash suffix to ensure uniqueness
        hash_suffix = hashlib.sha256(test_id.encode()).hexdigest()[:8]
        prefix_length = available_length - len(hash_suffix) - 1
        sanitized = f"{sanitized[:prefix_length]}_{hash_suffix}"
    return sanitized


@pytest.fixture
def test_db(
    request: pytest.FixtureRequest, block_production_config_in_tests: Callable
) -> Generator[DatabaseConfig, None, None]:
    """Create isolated database for each test.

    Creates a unique database per test, initializes schema, and drops it after.
    Safe for parallel pytest-xdist execution - each test gets its own database.

    Database name is derived from the test node ID for better debuggability.

    Yields:
        DatabaseConfig for the test database (with both admin and agent credentials)
    """
    # Generate database name from test node ID
    test_node_id = request.node.nodeid
    sanitized_id = _sanitize_test_id(test_node_id)
    db_name = f"props_test_{sanitized_id}"

    # Get base config (uses the original function, bypassing the mock)
    get_database_config_original = block_production_config_in_tests
    base_config = get_database_config_original()  # Uses env vars set by devenv

    # Create test database (idempotent - drops existing if present)
    ensure_database_exists(base_config, db_name, drop_existing=True)

    # Build config for the new test database
    test_config = base_config.with_database(db_name)

    # Keep postgres engine for teardown
    postgres_config = base_config.with_database("postgres")
    postgres_engine = create_engine(postgres_config.admin_url(), isolation_level="AUTOCOMMIT")

    # Dispose any existing connection (needed for per-test isolation in parallel tests)

    dispose_db()

    # Initialize schema in the new database
    init_db(test_config)
    recreate_database()

    yield test_config  # Test runs here with access to config

    # Cleanup: drop the test database
    with postgres_engine.connect() as conn:
        # Terminate connections to the test database
        conn.execute(
            text(
                f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_name}'
              AND pid <> pg_backend_pid()
        """
            )
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))

    postgres_engine.dispose()


@pytest.fixture
def admin_engine(test_db: DatabaseConfig) -> Generator:
    """Create admin engine for test database with proper disposal.

    Use this instead of manually creating engines in tests.
    Automatically disposes the engine after the test completes.

    Args:
        test_db: Test database configuration fixture

    Yields:
        SQLAlchemy Engine configured with admin credentials for the test database
    """

    engine = create_engine(test_db.admin_url())
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def test_snapshot(synced_test_fixtures) -> SnapshotSlug:
    """Use test-fixtures/test-trivial snapshot from git fixtures.

    Returns test-fixtures/test-trivial slug which is already synced by synced_test_fixtures.

    Returns:
        SnapshotSlug for the git fixture snapshot
    """
    # Use git fixture snapshot (already synced via synced_test_fixtures)
    return SnapshotSlug("test-fixtures/test-trivial")


@pytest.fixture
def synced_test_db(test_db: DatabaseConfig) -> DatabaseConfig:
    """Test database with production specimens synced.

    Uses production CLI sync code to sync snapshots, issues, examples,
    detector prompts, and model metadata.
    """
    sync_all()
    return test_db


@pytest.fixture
def synced_test_fixtures(test_db: DatabaseConfig, monkeypatch: pytest.MonkeyPatch) -> DatabaseConfig:
    """Test database with test fixture specimens synced (not production).

    Syncs test-trivial and test-validation from tests/props/fixtures/specimens/.
    These are git-tracked fixtures with known issues for faster, hermetic testing.

    Uses production CLI sync code via environment override.
    """
    # Override specimens path to point to test fixtures
    test_fixtures_path = Path(__file__).parent / "fixtures" / "specimens"
    monkeypatch.setenv("ADGN_PROPS_SPECIMENS_ROOT", str(test_fixtures_path))

    # Use production sync code with test fixtures path
    sync_all()

    return test_db


@pytest.fixture
def test_validation_snapshot_slug(synced_test_fixtures: DatabaseConfig) -> SnapshotSlug:
    """Return test-validation fixture snapshot slug (after syncing test fixtures).

    Test fixture snapshot with issues (TPs/FPs) for validation.
    Lives in tests/props/fixtures/specimens/test-fixtures/test-validation/.
    """
    return SnapshotSlug("test-fixtures/test-validation")


def _make_example_with_runs(
    slug: SnapshotSlug, found_credit: float, test_prompt_sha: str
) -> tuple[Example, CriticRun, GraderRun]:
    """Helper to create example with critic and grader runs.

    Args:
        slug: Snapshot slug to query
        found_credit: Credit value for grader output (0.0-1.0)
        test_prompt_sha: Prompt SHA256 hash

    Returns:
        Tuple of (example, critic_run, grader_run)
    """
    with get_session() as session:
        example = session.query(Example).filter_by(snapshot_slug=slug).first()
        assert example, f"No examples found for {slug}"

        critic_run = make_critic_run(example=example, prompt_sha256=test_prompt_sha)
        session.add(critic_run)
        session.flush()

        grader_run = make_grader_run(critic_run=critic_run)
        session.add(grader_run)
        session.commit()

        return (example, critic_run, grader_run)


@pytest.fixture
def test_trivial_snapshot(synced_test_fixtures: DatabaseConfig) -> Snapshot:
    """Provide the test-trivial snapshot (train split).

    This is a real git-tracked fixture with 2 TPs in add.py and subtract.py.
    Use this instead of creating synthetic snapshots.
    """
    with get_session() as session:
        return session.query(Snapshot).filter_by(slug="test-fixtures/test-trivial").one()


@pytest.fixture
def test_validation_snapshot(synced_test_fixtures: DatabaseConfig) -> Snapshot:
    """Provide the test-validation snapshot (valid split).

    This is a real git-tracked fixture with 1 TP in subtract.py.
    Use this instead of creating synthetic snapshots.
    """
    with get_session() as session:
        return session.query(Snapshot).filter_by(slug="test-fixtures/test-validation").one()


@pytest.fixture
def test_train_example_with_runs(
    synced_test_fixtures: DatabaseConfig, test_prompt_sha: str
) -> tuple[Example, CriticRun, GraderRun]:
    """Provide a train example with critic and grader runs.

    Uses test-trivial fixture (train split) and creates runs with 80% recall.
    Returns (example, critic_run, grader_run) tuple for test assertions.
    """
    return _make_example_with_runs(
        SnapshotSlug("test-fixtures/test-trivial"), found_credit=0.8, test_prompt_sha=test_prompt_sha
    )


@pytest.fixture
def test_valid_example_with_runs(
    synced_test_fixtures: DatabaseConfig, test_prompt_sha: str
) -> tuple[Example, CriticRun, GraderRun]:
    """Provide a valid example with critic and grader runs.

    Uses test-validation fixture (valid split) and creates runs with 60% recall.
    Returns (example, critic_run, grader_run) tuple for test assertions.
    """
    return _make_example_with_runs(
        SnapshotSlug("test-fixtures/test-validation"), found_credit=0.6, test_prompt_sha=test_prompt_sha
    )
