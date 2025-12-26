"""Test that failed critic runs appear in occurrence_credits view with zero credit."""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from props.db.agent_definition_ids import CRITIC_AGENT_DEFINITION_ID
from props.db.examples import Example
from props.db.models import (
    AgentRun,
    AgentRunStatus,
    FileSet,
    FileSetMember,
    OccurrenceTrigger,
    RecallByDefinitionSplitKind,
    RecallByExample,
    Snapshot,
    SnapshotFile,
    TruePositive,
    TruePositiveOccurrenceORM,
)
from props.db.sync.sync import compute_files_hash
from props.grader.models import GraderSuccess, InputIssueID, OccurrenceMatch, OccurrenceResult, TruePositiveID
from props.ids import SnapshotSlug
from props.models.examples import ExampleKind, SingleFileSetExample
from props.models.snapshot import LocalSource
from props.rationale import Rationale
from props.splits import Split
from tests.conftest import (
    EMPTY_CANONICAL_ISSUES_SNAPSHOT,
    make_critic_run,
    make_grader_run,
    make_reported_issues,
    populate_grading_decisions,
)


def make_tp_with_occurrence(
    session: Session,
    snapshot_slug: SnapshotSlug,
    tp_id: str,
    rationale: str,
    occurrence_id: str,
    files: dict[str, list[tuple[int, int]] | None],
    expect_caught_from: list[list[str]],
    note: str | None = None,
) -> TruePositive:
    """Create a TruePositive with a single occurrence using ORM models.

    Args:
        session: Database session
        snapshot_slug: Snapshot slug
        tp_id: True positive ID
        rationale: Issue rationale
        occurrence_id: Occurrence ID
        files: Dict of {path: line_ranges or None}
        expect_caught_from: List of trigger sets, each a list of file paths
        note: Optional note

    Returns:
        TruePositive ORM object (added to session but not flushed)
    """
    tp = TruePositive(snapshot_slug=snapshot_slug, tp_id=tp_id, rationale=rationale)
    session.add(tp)
    session.flush()  # Need to flush TP before adding occurrence

    occ = TruePositiveOccurrenceORM(
        snapshot_slug=snapshot_slug,
        tp_id=tp_id,
        occurrence_id=occurrence_id,
        files=files,
        expect_caught_from=expect_caught_from,
        note=note,
    )
    session.add(occ)
    return tp


@dataclass
class CriticRunFactory:
    """Factory for creating critic runs in tests.

    Uses git-synced fixtures (test-fixtures/test-trivial) instead of synthetic data.
    """

    session: Session
    example: Example

    @property
    def snapshot_slug(self) -> SnapshotSlug:
        return self.example.snapshot_slug

    def create_successful(self):
        """Create a successful critic run with grader run."""
        # Create critic run
        critic_run = make_critic_run(example=self.example, status=AgentRunStatus.COMPLETED)
        self.session.add(critic_run)
        self.session.flush()

        # Create grader run with zero occurrences found
        # Note: We use the git fixture's TP ID (test-issue) - but we don't need to know it
        # because we're testing the aggregation logic, not the grading logic
        grader_run = make_grader_run(
            critic_run=critic_run, model="test-grader-model", canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT
        )
        self.session.add(grader_run)
        self.session.flush()  # Ensure grader_run.agent_run_id is available

    def create_failed(self, status: AgentRunStatus):
        """Create a failed critic run with the given status."""
        critic_run = make_critic_run(example=self.example, status=status)
        self.session.add(critic_run)


@pytest.fixture
def critic_run_factory():
    """Factory for creating critic runs using git-synced test fixtures.

    Uses test-fixtures/test-trivial with the subtract.py file-set example (has exactly 1 TP).
    Returns a factory function that takes a session and returns a CriticRunFactory.
    """

    def _make_factory(session: Session) -> CriticRunFactory:
        # Use git-synced fixture: test-fixtures/test-trivial has 4 TPs
        # Get the subtract.py file-set example (has exactly 1 catchable TP - test-issue)
        # Note: add.py and multiply.py file-sets have 2 catchable TPs each (test-issue-2/4 or test-issue-3/4)
        example = (
            session.query(Example)
            .filter_by(snapshot_slug=SnapshotSlug("test-fixtures/test-trivial"))
            .filter(Example.files_hash.isnot(None))
            .filter(Example.n_catchable_occurrences == 1)
            .first()
        )
        assert example is not None, "Expected single-file-set example with 1 catchable TP in test-trivial"
        return CriticRunFactory(session=session, example=example)

    return _make_factory


def create_critic_run_with_multiple_grader_runs(session: Session, example: Example, credits: list[float]) -> AgentRun:
    """Helper to create a successful critic run with multiple grader runs at different credits.

    Args:
        session: Database session
        example: Example to create critic run for
        credits: List of credit values for grader runs (one grader run per credit)

    Returns:
        The created AgentRun (already added to session and flushed)
    """
    critic_run = make_critic_run(example=example, model="test-model", status=AgentRunStatus.COMPLETED)
    session.add(critic_run)
    session.flush()

    # Pick a real TP occurrence from this snapshot (avoid synthetic IDs that violate FK trigger)
    tp_occ = (
        session.query(TruePositiveOccurrenceORM)
        .filter_by(snapshot_slug=example.snapshot_slug)
        .order_by(TruePositiveOccurrenceORM.tp_id, TruePositiveOccurrenceORM.occurrence_id)
        .first()
    )
    assert tp_occ is not None, "Expected at least one TP occurrence for example snapshot"

    # Create multiple grader runs with different credits
    for idx, credit in enumerate(credits):
        grader_success = GraderSuccess(
            occurrence_results=[
                OccurrenceResult(
                    tp_id=TruePositiveID(tp_occ.tp_id),
                    occurrence_id=tp_occ.occurrence_id,
                    found_credit=credit,
                    matched_by=[OccurrenceMatch(input_id=InputIssueID(f"input-{idx}"), credit=credit)],
                    rationale=Rationale(f"Credit {credit}"),
                )
            ],
            unknowns=[],
            summary=Rationale(f"Summary {credit}"),
        )

        # Create reported issue for this grader run
        make_reported_issues(agent_run_id=critic_run.agent_run_id, issue_ids=[f"input-{idx}"], session=session)

        grader_run = make_grader_run(
            critic_run=critic_run, model="test-grader-model", canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT
        )
        session.add(grader_run)
        session.flush()  # Ensure grader_run.agent_run_id is available

        # Populate grading_decisions table from MCP occurrence_results
        populate_grading_decisions(
            grader_run=grader_run, occurrence_results=grader_success.occurrence_results, session=session
        )

    return critic_run


def _create_synthetic_example(
    session: Session, snapshot_slug: SnapshotSlug, files: list[str], tp_id: str, occurrence_id: str
) -> Example:
    """Create synthetic file set and return the generated Example from VIEW.

    The Example VIEW auto-generates rows from OccurrenceTrigger entries.
    Creates the full chain: SnapshotFile → FileSet → FileSetMember → OccurrenceTrigger.

    Args:
        session: Database session
        snapshot_slug: Snapshot slug (must exist)
        files: List of file paths for the file set
        tp_id: TruePositive ID (must exist in the snapshot with occurrence)
        occurrence_id: Occurrence ID from the TruePositive

    Returns:
        Example ORM object from the VIEW
    """
    # Create SnapshotFile entries for FK validation
    for file_path in files:
        snapshot_file = SnapshotFile(snapshot_slug=snapshot_slug, relative_path=file_path, line_count=10)
        session.add(snapshot_file)

    session.flush()

    # Compute files_hash
    files_hash = compute_files_hash(files)

    # Create file set with computed hash
    fs = FileSet(snapshot_slug=snapshot_slug, files_hash=files_hash)
    session.add(fs)
    session.flush()

    # Create file set members
    for file_path in files:
        fsm = FileSetMember(files_hash=files_hash, file_path=file_path, snapshot_slug=snapshot_slug)
        session.add(fsm)

    # Create occurrence trigger linking TP occurrence to file set
    ot = OccurrenceTrigger(snapshot_slug=snapshot_slug, tp_id=tp_id, occurrence_id=occurrence_id, files_hash=files_hash)
    session.add(ot)

    session.flush()

    # Query the Example from VIEW
    return (
        session.query(Example)
        .filter_by(snapshot_slug=snapshot_slug, example_kind=ExampleKind.FILE_SET, files_hash=files_hash)
        .one()
    )


def _get_whole_snapshot_example(session: Session, snapshot_slug: SnapshotSlug) -> Example:
    """Get the whole-snapshot Example for a snapshot (auto-generated by VIEW).

    Args:
        session: Database session
        snapshot_slug: Snapshot slug (must exist)

    Returns:
        Example ORM object for whole-snapshot scope
    """
    return session.query(Example).filter_by(snapshot_slug=snapshot_slug, example_kind=ExampleKind.WHOLE_SNAPSHOT).one()


def test_failed_critic_run_appears_with_zero_credit(synced_test_session: Session):
    """Test that max_turns_exceeded critic runs generate zero-credit rows for catchable occurrences."""
    snapshot_slug = SnapshotSlug("test-failure/2025-01-01-00")

    # Files for the critic run
    files = ["test/file1.py"]

    # Insert snapshot
    snapshot = Snapshot(slug=snapshot_slug, split=Split.TRAIN, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    # Insert TruePositive with occurrence catchable from file1.py
    make_tp_with_occurrence(
        synced_test_session,
        snapshot_slug=snapshot_slug,
        tp_id="test-tp-001",
        rationale="Test issue catchable from file1",
        occurrence_id="occ-1",
        files={"test/file1.py": None},
        expect_caught_from=[["test/file1.py"]],
    )
    synced_test_session.flush()

    # Create synthetic example via trigger set (uses the TP we just created)
    example = _create_synthetic_example(
        synced_test_session, snapshot_slug, files, tp_id="test-tp-001", occurrence_id="occ-1"
    )

    # Insert failed critic run (max_turns_exceeded, no critique)
    critic_run = make_critic_run(example=example, model="test-critic-model", status=AgentRunStatus.MAX_TURNS_EXCEEDED)
    synced_test_session.add(critic_run)
    synced_test_session.commit()

    # Query occurrence_credits view - should include zero-credit row for the catchable occurrence
    result = synced_test_session.execute(
        text(
            """
            SELECT critic_run_id, tp_id, occurrence_id, found_credit, grader_rationale
            FROM occurrence_credits
            WHERE snapshot_slug = :slug
        """
        ),
        {"slug": str(snapshot_slug)},
    ).fetchone()

    assert result is not None, "Failed critic run should generate zero-credit row"
    assert result.critic_run_id == critic_run.agent_run_id, "Should reference the failed critic run"
    assert result.tp_id == "test-tp-001", "Should include the catchable TP"
    assert result.occurrence_id == "occ-1", "Should include the catchable occurrence"
    assert result.found_credit == 0.0, "Failed run should have zero credit"
    assert "max_turns_exceeded" in result.grader_rationale, "Rationale should mention failure reason"


def test_context_length_exceeded_also_counted_as_zero(synced_test_session: Session):
    """Test that context_length_exceeded critic runs also generate zero-credit rows."""
    snapshot_slug = SnapshotSlug("test-context-failure/2025-01-01-00")

    files = ["test/file1.py"]

    snapshot = Snapshot(slug=snapshot_slug, split=Split.TRAIN, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    make_tp_with_occurrence(
        synced_test_session,
        snapshot_slug=snapshot_slug,
        tp_id="test-tp-002",
        rationale="Test issue",
        occurrence_id="occ-2",
        files={"test/file1.py": None},
        expect_caught_from=[["test/file1.py"]],
    )
    synced_test_session.flush()

    example = _create_synthetic_example(
        synced_test_session, snapshot_slug, files, tp_id="test-tp-002", occurrence_id="occ-2"
    )

    # Insert failed critic run (context_length_exceeded)
    critic_run = make_critic_run(
        example=example, model="test-critic-model", status=AgentRunStatus.CONTEXT_LENGTH_EXCEEDED
    )
    synced_test_session.add(critic_run)
    synced_test_session.commit()

    result = synced_test_session.execute(
        text(
            """
            SELECT found_credit, grader_rationale
            FROM occurrence_credits
            WHERE snapshot_slug = :slug
        """
        ),
        {"slug": str(snapshot_slug)},
    ).fetchone()

    assert result is not None
    assert result.found_credit == 0.0
    assert "context_length_exceeded" in result.grader_rationale


def test_only_catchable_occurrences_included_for_failures(synced_test_session: Session):
    """Test that failed runs only generate zero-credit rows for catchable occurrences."""
    snapshot_slug = SnapshotSlug("test-catchability/2025-01-01-00")

    # Review only file1.py
    files = ["test/file1.py"]

    snapshot = Snapshot(slug=snapshot_slug, split=Split.TRAIN, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    # TP1: Catchable from file1.py (should appear in view)
    make_tp_with_occurrence(
        synced_test_session,
        snapshot_slug=snapshot_slug,
        tp_id="catchable-tp",
        rationale="Issue catchable from file1",
        occurrence_id="catchable-occ",
        files={"test/file1.py": None},
        expect_caught_from=[["test/file1.py"]],
    )

    # TP2: NOT catchable from file1.py alone (requires file2.py - should NOT appear)
    make_tp_with_occurrence(
        synced_test_session,
        snapshot_slug=snapshot_slug,
        tp_id="not-catchable-tp",
        rationale="Issue requires both files",
        occurrence_id="not-catchable-occ",
        files={"test/file1.py": None, "test/file2.py": None},
        expect_caught_from=[["test/file1.py", "test/file2.py"]],
    )
    synced_test_session.flush()

    # Create example from the catchable TP
    example = _create_synthetic_example(
        synced_test_session, snapshot_slug, files, tp_id="catchable-tp", occurrence_id="catchable-occ"
    )

    critic_run = make_critic_run(example=example, model="test-critic-model", status=AgentRunStatus.MAX_TURNS_EXCEEDED)
    synced_test_session.add(critic_run)
    synced_test_session.commit()

    # Should only see the catchable occurrence
    results = synced_test_session.execute(
        text(
            """
            SELECT tp_id, occurrence_id
            FROM occurrence_credits
            WHERE snapshot_slug = :slug
            ORDER BY tp_id
        """
        ),
        {"slug": str(snapshot_slug)},
    ).fetchall()

    assert len(results) == 1, "Should only include catchable occurrence"
    assert results[0].tp_id == "catchable-tp"
    assert results[0].occurrence_id == "catchable-occ"


def test_whole_snapshot_failure_includes_all_occurrences(synced_test_session: Session):
    """Test that whole-snapshot failed runs include all occurrences (no catchability filtering)."""
    snapshot_slug = SnapshotSlug("test-whole-snapshot-failure/2025-01-01-00")

    snapshot = Snapshot(slug=snapshot_slug, split=Split.VALID, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    # Add multiple TPs with different expect_caught_from
    make_tp_with_occurrence(
        synced_test_session,
        snapshot_slug=snapshot_slug,
        tp_id="tp-issue-1",
        rationale="Issue 1",
        occurrence_id="occ-issue-1",
        files={"test/file1.py": None},
        expect_caught_from=[["test/file1.py"]],
    )

    make_tp_with_occurrence(
        synced_test_session,
        snapshot_slug=snapshot_slug,
        tp_id="tp-issue-2",
        rationale="Issue 2",
        occurrence_id="occ-issue-2",
        files={"test/file2.py": None},
        expect_caught_from=[["test/file2.py"]],
    )
    synced_test_session.flush()

    # Whole-snapshot example (auto-generated by VIEW)
    example = _get_whole_snapshot_example(synced_test_session, snapshot_slug)

    # Failed critic run for whole-snapshot
    critic_run = make_critic_run(example=example, model="test-critic-model", status=AgentRunStatus.MAX_TURNS_EXCEEDED)
    synced_test_session.add(critic_run)
    synced_test_session.commit()

    # Should include ALL occurrences (no catchability filtering for whole-snapshot)
    results = synced_test_session.execute(
        text(
            """
            SELECT tp_id, occurrence_id
            FROM occurrence_credits
            WHERE snapshot_slug = :slug
            ORDER BY tp_id
        """
        ),
        {"slug": str(snapshot_slug)},
    ).fetchall()

    assert len(results) == 2, "Whole-snapshot failure should include all occurrences"
    assert results[0].tp_id == "tp-issue-1"
    assert results[0].occurrence_id == "occ-issue-1"
    assert results[1].tp_id == "tp-issue-2"
    assert results[1].occurrence_id == "occ-issue-2"


def test_successful_run_not_affected_by_failure_logic(synced_test_session: Session):
    """Test that successful critic+grader runs still work correctly (not affected by UNION ALL)."""
    snapshot_slug = SnapshotSlug("test-success-unaffected/2025-01-01-00")
    grader_agent_run_id = uuid4()

    files = ["test/file1.py"]

    snapshot = Snapshot(slug=snapshot_slug, split=Split.TRAIN, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    make_tp_with_occurrence(
        synced_test_session,
        snapshot_slug=snapshot_slug,
        tp_id="success-tp",
        rationale="Test issue",
        occurrence_id="success-occ",
        files={"test/file1.py": None},
        expect_caught_from=[["test/file1.py"]],
    )
    synced_test_session.flush()

    example = _create_synthetic_example(
        synced_test_session, snapshot_slug, files, tp_id="success-tp", occurrence_id="success-occ"
    )

    # Successful critic run
    critic_run = make_critic_run(example=example, model="test-critic-model", status=AgentRunStatus.COMPLETED)
    synced_test_session.add(critic_run)
    synced_test_session.flush()

    # Successful grader run
    grader_success = GraderSuccess(
        occurrence_results=[
            OccurrenceResult(
                tp_id=TruePositiveID("success-tp"),
                occurrence_id="success-occ",
                found_credit=0.8,
                matched_by=[OccurrenceMatch(input_id=InputIssueID("input-1"), credit=0.8)],
                rationale=Rationale("Partially found"),
            )
        ],
        unknowns=[],
        summary=Rationale("Test summary"),
    )

    # Create reported issue for this grader run (use test/file1.py which exists in this synthetic snapshot)
    make_reported_issues(
        agent_run_id=critic_run.agent_run_id,
        issue_ids=["input-1"],
        session=synced_test_session,
        location_file="test/file1.py",
    )

    grader_run = make_grader_run(
        critic_run=critic_run,
        model="test-grader-model",
        canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
        agent_run_id=grader_agent_run_id,
    )
    synced_test_session.add(grader_run)
    synced_test_session.flush()  # Ensure grader_run.agent_run_id is available

    # Populate grading_decisions table from MCP occurrence_results
    populate_grading_decisions(
        grader_run=grader_run, occurrence_results=grader_success.occurrence_results, session=synced_test_session
    )

    synced_test_session.commit()

    # Should see the successful run with actual found_credit
    result = synced_test_session.execute(
        text(
            """
            SELECT grader_run_id, found_credit, grader_rationale
            FROM occurrence_credits
            WHERE snapshot_slug = :slug
        """
        ),
        {"slug": str(snapshot_slug)},
    ).fetchone()

    assert result is not None
    assert result.grader_run_id is not None, "Successful run should have grader_run_id"
    assert result.found_credit == 0.8, "Should have actual found_credit from grader"
    assert "Partially found" in result.grader_rationale, "Should have actual grader rationale"


def test_multiple_occurrences_with_or_logic_in_expect_caught_from(synced_test_session: Session):
    """Test catchability with OR logic: expect_caught_from with multiple trigger sets."""
    snapshot_slug = SnapshotSlug("test-or-logic/2025-01-01-00")

    # Review only file1.py
    files = ["test/file1.py"]

    snapshot = Snapshot(slug=snapshot_slug, split=Split.TRAIN, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    # TP with OR logic: catchable from EITHER file1.py OR file2.py
    make_tp_with_occurrence(
        synced_test_session,
        snapshot_slug=snapshot_slug,
        tp_id="or-logic-tp",
        rationale="Duplication - catchable from either file",
        occurrence_id="or-occ",
        files={"test/file1.py": None, "test/file2.py": None},
        # OR logic: either file triggers detection
        expect_caught_from=[["test/file1.py"], ["test/file2.py"]],
    )
    synced_test_session.flush()

    example = _create_synthetic_example(
        synced_test_session, snapshot_slug, files, tp_id="or-logic-tp", occurrence_id="or-occ"
    )

    critic_run = make_critic_run(example=example, model="test-critic-model", status=AgentRunStatus.MAX_TURNS_EXCEEDED)
    synced_test_session.add(critic_run)
    synced_test_session.commit()

    # Should be catchable because file1.py satisfies one of the trigger sets
    result = synced_test_session.execute(
        text(
            """
            SELECT tp_id, occurrence_id
            FROM occurrence_credits
            WHERE snapshot_slug = :slug
        """
        ),
        {"slug": str(snapshot_slug)},
    ).fetchone()

    assert result is not None, "Occurrence should be catchable via OR logic"
    assert result.tp_id == "or-logic-tp"
    assert result.occurrence_id == "or-occ"


def test_multiple_grader_runs_do_not_overweight_critic_run(synced_test_session: Session, critic_run_factory):
    """Test that multiple grader runs for same critic run don't cause overweighting.

    Regression test for weighting issue where a critic run graded N times
    would contribute N rows instead of 1 row (with averaged credit).
    """
    factory = critic_run_factory(synced_test_session)

    # Create 1 failed critic run (0 credit)
    factory.create_failed(AgentRunStatus.MAX_TURNS_EXCEEDED)

    # Create 1 successful critic run with 3 grader runs at different credits
    create_critic_run_with_multiple_grader_runs(
        session=synced_test_session, example=factory.example, credits=[0.5, 0.6, 0.7]
    )

    synced_test_session.commit()

    # Query aggregated view using ORM (occurrence-based weighting)
    result = (
        synced_test_session.query(RecallByDefinitionSplitKind)
        .filter_by(critic_definition_id=CRITIC_AGENT_DEFINITION_ID, split=Split.TRAIN, critic_model="test-model")
        .one()
    )

    assert result is not None, "Should have aggregated metrics"

    # Expected behavior (with correct weighting):
    # - 2 critic runs total: 1 successful, 1 max_turns_exceeded
    # - 1 example with 1 catchable occurrence (test-issue in subtract.py)
    #
    # Aggregation logic:
    # - n_catchable_occurrences: Sum across distinct examples = 1
    # - credit_stats.mean: AVG across runs of per-run mean credit
    #   - Failed run: counts as 0 credit
    #   - Successful run: avg(0.5, 0.6, 0.7) = 0.6 credit (averaged across grader runs)
    #   - Mean: (0.0 + 0.6) / 2 = 0.3
    # - recall = 0.3 / 1 = 0.3 (30% of catchable occurrences found on average)
    assert sum(result.status_counts.values()) == 2, "Should count both critic runs"
    assert result.status_counts[AgentRunStatus.COMPLETED] == 1
    assert result.status_counts[AgentRunStatus.MAX_TURNS_EXCEEDED] == 1

    # Check aggregated values
    avg_caught = result.credit_stats.mean if result.credit_stats else 0.0
    assert abs(avg_caught - 0.3) < 0.01, f"credit_stats.mean should be 0.3, got {avg_caught}"

    # n_catchable_occurrences: Sum across distinct examples (not runs)
    # This example has 1 catchable occurrence, so the sum is 1
    assert result.n_catchable_occurrences == 1, (
        f"n_catchable_occurrences should be 1 (sum across examples), got {result.n_catchable_occurrences}"
    )

    # Compute and check recall
    recall = avg_caught / float(result.n_catchable_occurrences)
    assert abs(recall - 0.3) < 0.01, f"Recall should be 0.3 (0.3/1.0), got {recall}"

    # Without the fix, multiple grader runs would cause overweighting:
    # - Would incorrectly count 4 occurrence-runs (1 failed + 3 grader rows)
    # - Would compute avg_caught as 0.45 instead of 0.3


def test_aggregated_view_counts_total_and_failed_runs(synced_test_session: Session, critic_run_factory):
    """Test that aggregated_recall_by_definition includes n_successful and failure counts."""
    factory = critic_run_factory(synced_test_session)

    # Create 3 successful runs
    for _i in range(3):
        factory.create_successful()

    # Create 2 max_turns_exceeded failures
    for _i in range(2):
        factory.create_failed(AgentRunStatus.MAX_TURNS_EXCEEDED)

    # Create 1 context_length_exceeded failure
    factory.create_failed(AgentRunStatus.CONTEXT_LENGTH_EXCEEDED)

    synced_test_session.commit()

    # Query aggregated view using ORM (occurrence-based weighting)
    result = (
        synced_test_session.query(RecallByDefinitionSplitKind)
        .filter_by(critic_definition_id=CRITIC_AGENT_DEFINITION_ID, split=Split.TRAIN, critic_model="test-model")
        .one()
    )

    assert result is not None, "Should have aggregated metrics"
    assert sum(result.status_counts.values()) == 6, "Should count all 6 critic runs"
    assert result.status_counts[AgentRunStatus.COMPLETED] == 3
    assert result.status_counts[AgentRunStatus.MAX_TURNS_EXCEEDED] == 2
    assert result.status_counts[AgentRunStatus.CONTEXT_LENGTH_EXCEEDED] == 1


def test_aggregated_view_counts_zero_when_no_failures(synced_test_session: Session, critic_run_factory):
    """Test that failure counts are zero when all runs succeed."""
    factory = critic_run_factory(synced_test_session)

    # Create only successful runs
    for _i in range(3):
        factory.create_successful()

    synced_test_session.commit()

    # Query aggregated view using ORM (occurrence-based weighting)
    result = (
        synced_test_session.query(RecallByDefinitionSplitKind)
        .filter_by(critic_definition_id=CRITIC_AGENT_DEFINITION_ID, split=Split.TRAIN, critic_model="test-model")
        .one()
    )

    assert result is not None, "Should have aggregated metrics"
    assert sum(result.status_counts.values()) == 3, "Should count all 3 runs"
    assert result.status_counts[AgentRunStatus.COMPLETED] == 3
    assert result.status_counts.get(AgentRunStatus.MAX_TURNS_EXCEEDED, 0) == 0
    assert result.status_counts.get(AgentRunStatus.CONTEXT_LENGTH_EXCEEDED, 0) == 0


def test_aggregated_recall_by_example_has_correct_weighting(synced_test_session: Session, critic_run_factory):
    """Test that aggregated_recall_by_example correctly weights critic runs (not grader runs)."""
    factory = critic_run_factory(synced_test_session)
    snapshot_slug = factory.snapshot_slug
    example = factory.example

    # Create 1 failed critic run
    factory.create_failed(AgentRunStatus.MAX_TURNS_EXCEEDED)

    # Create 1 successful critic run with 3 grader runs at different credits
    create_critic_run_with_multiple_grader_runs(session=synced_test_session, example=example, credits=[0.4, 0.5, 0.6])

    synced_test_session.commit()

    # Query aggregated_recall_by_example using ORM (occurrence-based weighting)
    # Filter by the example's actual fields
    result = (
        synced_test_session.query(RecallByExample)
        .filter_by(snapshot_slug=snapshot_slug, example_kind=example.example_kind, files_hash=example.files_hash)
        .one()
    )

    assert result is not None, "Should have example metrics"

    # Count critic runs
    assert sum(result.status_counts.values()) == 2, "Should count 2 critic runs"
    assert result.status_counts[AgentRunStatus.COMPLETED] == 1
    assert result.status_counts[AgentRunStatus.MAX_TURNS_EXCEEDED] == 1
    assert result.status_counts.get(AgentRunStatus.CONTEXT_LENGTH_EXCEEDED, 0) == 0

    # Occurrence-based weighting (per-example view):
    # - This example has 1 catchable occurrence (test-issue in subtract.py)
    # - n_catchable_occurrences: MAX per example (constant) = 1
    # - credit_stats.mean: AVG across runs
    #   - Failed run: counts as 0 credit
    #   - Successful run: avg(0.4, 0.5, 0.6) = 0.5 credit
    #   - Mean: (0.0 + 0.5) / 2 = 0.25
    # - recall = 0.25 / 1 = 0.25
    avg_caught = result.credit_stats.mean if result.credit_stats else 0.0
    assert abs(avg_caught - 0.25) < 0.01, f"Expected 0.25, got {avg_caught}"

    # n_catchable_occurrences: MAX per example (it's constant for this example = 1)
    assert result.n_catchable_occurrences == 1, (
        f"Expected 1 (one catchable occurrence in example), got {result.n_catchable_occurrences}"
    )

    # Compute recall
    recall = avg_caught / float(result.n_catchable_occurrences)
    assert abs(recall - 0.25) < 0.01, f"Expected recall 0.25 (0.25/1.0), got {recall}"


def test_occurrence_statistics_has_correct_n_critic_runs(
    synced_test_session: Session, subtract_file_example: SingleFileSetExample
):
    """Test that aggregated_recall_by_example counts critic runs correctly (not grader runs)."""
    # Use git-synced fixture: test-fixtures/test-trivial with subtract.py scope
    snapshot_slug = subtract_file_example.snapshot_slug

    # Get the example for critic run creation
    example = Example.from_spec(synced_test_session, subtract_file_example)

    # Create 2 critic runs with different numbers of grader runs
    # Critic run 1: graded 1 time (credit 0.8)
    create_critic_run_with_multiple_grader_runs(session=synced_test_session, example=example, credits=[0.8])

    # Critic run 2: graded 4 times (credits 0.5, 0.6, 0.7, 0.8)
    create_critic_run_with_multiple_grader_runs(
        session=synced_test_session, example=example, credits=[0.5, 0.6, 0.7, 0.8]
    )

    synced_test_session.commit()

    # Query aggregated_recall_by_example using ORM (occurrence-based weighting)
    result = (
        synced_test_session.query(RecallByExample)
        .filter_by(snapshot_slug=snapshot_slug, example_kind=example.example_kind, files_hash=example.files_hash)
        .one()
    )

    assert result is not None, "Should have aggregated stats for example"

    # Should count 2 critic runs, not 5 grader runs
    assert sum(result.status_counts.values()) == 2, "Should count 2 critic runs"
    assert result.status_counts[AgentRunStatus.COMPLETED] == 2

    # Occurrence-based weighting:
    # - Run 1: credit_stats.mean = 0.8 (1 grader)
    # - Run 2: credit_stats.mean = avg(0.5, 0.6, 0.7, 0.8) = 0.65 (4 graders averaged)
    # - avg_occurrences_caught = (0.8 + 0.65) / 2 = 0.725
    # - n_catchable_occurrences = 1 (one occurrence)
    # - recall = 0.725 / 1.0 = 0.725
    avg_caught = result.credit_stats.mean if result.credit_stats else 0.0
    assert abs(avg_caught - 0.725) < 0.01, f"Expected 0.725, got {avg_caught}"
    assert abs(result.n_catchable_occurrences - 1.0) < 0.01, f"Expected 1.0, got {result.n_catchable_occurrences}"

    # Compute recall
    recall = avg_caught / float(result.n_catchable_occurrences)
    assert abs(recall - 0.725) < 0.01, f"Expected recall 0.725, got {recall}"
