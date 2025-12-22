"""Test that failed critic runs appear in occurrence_credits view with zero credit."""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from adgn.props.db.agent_definition_ids import CRITIC_AGENT_DEFINITION_ID
from adgn.props.db.examples import Example
from adgn.props.db.models import (
    AgentRun,
    AgentRunStatus,
    AggregatedRecallByDefinition,
    AggregatedRecallByExample,
    Snapshot,
    TruePositive,
)
from adgn.props.grader.models import GraderSuccess, InputIssueID, OccurrenceMatch, OccurrenceResult, TruePositiveID
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import ExplicitFileScope
from adgn.props.models.snapshot import LocalSource
from adgn.props.models.true_positive import TruePositiveOccurrence
from adgn.props.rationale import Rationale
from adgn.props.splits import Split
from tests.conftest import EMPTY_CANONICAL_ISSUES_SNAPSHOT
from tests.props.conftest import make_critic_run, make_grader_run, make_reported_issues, populate_grading_decisions


@pytest.fixture
def basic_snapshot_with_tp():
    """Fixture providing a snapshot with one TP occurrence."""
    snapshot_slug = SnapshotSlug(f"test-basic/{uuid4()}")
    files = ["test/file1.py"]

    def _create(session):
        snapshot = Snapshot(slug=snapshot_slug, split=Split.TRAIN, source=LocalSource(vcs="local", root="."))
        session.add(snapshot)

        tp1 = TruePositive(
            snapshot_slug=snapshot_slug,
            tp_id="test-tp-001",
            rationale="Test issue",
            occurrences=[
                TruePositiveOccurrence(
                    occurrence_id="occ-1",
                    files={Path("test/file1.py"): None},
                    expect_caught_from={frozenset([Path("test/file1.py")])},
                    note=None,
                )
            ],
        )
        session.add(tp1)

        scope = ExplicitFileScope(files=files)
        example = Example.from_scope(snapshot_slug, scope)
        session.add(example)
        session.commit()

        return snapshot_slug, example.scope_hash

    return _create


@dataclass
class CriticRunFactory:
    """Factory for creating critic runs in tests."""

    session: Session
    snapshot_slug: SnapshotSlug
    scope_hash: str

    def create_successful(self):
        """Create a successful critic run with grader run."""
        # Get the example for this critic run
        example = (
            self.session.query(Example).filter_by(snapshot_slug=self.snapshot_slug, scope_hash=self.scope_hash).one()
        )

        # Create critic run
        critic_run = make_critic_run(example=example, status=AgentRunStatus.COMPLETED)
        self.session.add(critic_run)
        self.session.flush()

        # Create grader run with zero occurrences found
        grader_success = GraderSuccess(
            occurrence_results=[
                OccurrenceResult(
                    tp_id=TruePositiveID("test-tp-001"),
                    occurrence_id="occ-1",
                    found_credit=0.0,
                    matched_by=[],  # Empty matched_by means occurrence not found
                    rationale=Rationale("Occurrence not found in critique"),
                )
            ],
            unknowns=[],
            summary=Rationale("No issues found in critique"),
        )
        grader_run = make_grader_run(
            critic_run=critic_run, model="test-grader-model", canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT
        )
        self.session.add(grader_run)
        self.session.flush()  # Ensure grader_run.agent_run_id is available

        # Populate grading_decisions table from MCP occurrence_results
        # Note: matched_by is empty, so no grading decisions will be created
        populate_grading_decisions(
            grader_run=grader_run, occurrence_results=grader_success.occurrence_results, session=self.session
        )

    def create_failed(self, status: AgentRunStatus):
        """Create a failed critic run with the given status."""
        # Get the example for this critic run
        example = (
            self.session.query(Example).filter_by(snapshot_slug=self.snapshot_slug, scope_hash=self.scope_hash).one()
        )

        critic_run = make_critic_run(example=example, status=status)
        self.session.add(critic_run)


@pytest.fixture
def critic_run_factory(basic_snapshot_with_tp):
    """Factory for creating critic runs with common parameters captured.

    Returns a factory function that takes a session and returns a CriticRunFactory.
    """

    def _make_factory(session):
        snapshot_slug, scope_hash = basic_snapshot_with_tp(session)
        return CriticRunFactory(session=session, snapshot_slug=snapshot_slug, scope_hash=scope_hash)

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

    # Create multiple grader runs with different credits
    for idx, credit in enumerate(credits):
        grader_success = GraderSuccess(
            occurrence_results=[
                OccurrenceResult(
                    tp_id=TruePositiveID("test-tp-001"),
                    occurrence_id="occ-1",
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


def test_failed_critic_run_appears_with_zero_credit(synced_test_session: Session):
    """Test that max_turns_exceeded critic runs generate zero-credit rows for catchable occurrences."""
    snapshot_slug = SnapshotSlug("test-failure/2025-01-01-00")

    # Files for the critic run
    files = ["test/file1.py"]

    # Insert snapshot
    snapshot = Snapshot(slug=snapshot_slug, split=Split.TRAIN, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    # Insert TruePositive with occurrence catchable from file1.py
    tp1 = TruePositive(
        snapshot_slug=snapshot_slug,
        tp_id="test-tp-001",
        rationale="Test issue catchable from file1",
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id="occ-1",
                files={Path("test/file1.py"): None},
                expect_caught_from={frozenset([Path("test/file1.py")])},
                note=None,
            )
        ],
    )
    synced_test_session.add(tp1)

    # Insert example (file-set)
    scope = ExplicitFileScope(files=files)
    example = Example.from_scope(snapshot_slug, scope)
    synced_test_session.add(example)

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

    tp1 = TruePositive(
        snapshot_slug=snapshot_slug,
        tp_id="test-tp-002",
        rationale="Test issue",
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id="occ-2",
                files={Path("test/file1.py"): None},
                expect_caught_from={frozenset([Path("test/file1.py")])},
                note=None,
            )
        ],
    )
    synced_test_session.add(tp1)

    scope = ExplicitFileScope(files=files)
    example = Example.from_scope(snapshot_slug, scope)
    synced_test_session.add(example)

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
    tp1 = TruePositive(
        snapshot_slug=snapshot_slug,
        tp_id="catchable-tp",
        rationale="Issue catchable from file1",
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id="catchable-occ",
                files={Path("test/file1.py"): None},
                expect_caught_from={frozenset([Path("test/file1.py")])},
                note=None,
            )
        ],
    )
    synced_test_session.add(tp1)

    # TP2: NOT catchable from file1.py alone (requires file2.py - should NOT appear)
    tp2 = TruePositive(
        snapshot_slug=snapshot_slug,
        tp_id="not-catchable-tp",
        rationale="Issue requires both files",
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id="not-catchable-occ",
                files={Path("test/file1.py"): None, Path("test/file2.py"): None},
                expect_caught_from={frozenset([Path("test/file1.py"), Path("test/file2.py")])},
                note=None,
            )
        ],
    )
    synced_test_session.add(tp2)

    scope = ExplicitFileScope(files=files)
    example = Example.from_scope(snapshot_slug, scope)
    synced_test_session.add(example)

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


def test_whole_snapshot_failure_includes_all_occurrences(synced_test_session: Session, all_files_scope):
    """Test that whole-snapshot failed runs include all occurrences (no catchability filtering)."""
    snapshot_slug = SnapshotSlug("test-whole-snapshot-failure/2025-01-01-00")

    snapshot = Snapshot(slug=snapshot_slug, split=Split.VALID, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    # Add multiple TPs with different expect_caught_from
    tp1 = TruePositive(
        snapshot_slug=snapshot_slug,
        tp_id="tp-1",
        rationale="Issue 1",
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id="occ-1",
                files={Path("test/file1.py"): None},
                expect_caught_from={frozenset([Path("test/file1.py")])},
                note=None,
            )
        ],
    )
    synced_test_session.add(tp1)

    tp2 = TruePositive(
        snapshot_slug=snapshot_slug,
        tp_id="tp-2",
        rationale="Issue 2",
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id="occ-2",
                files={Path("test/file2.py"): None},
                expect_caught_from={frozenset([Path("test/file2.py")])},
                note=None,
            )
        ],
    )
    synced_test_session.add(tp2)

    # Whole-snapshot example (use fixture)
    example = Example.from_scope(snapshot_slug, all_files_scope)
    synced_test_session.add(example)

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
    assert results[0].tp_id == "tp-1"
    assert results[0].occurrence_id == "occ-1"
    assert results[1].tp_id == "tp-2"
    assert results[1].occurrence_id == "occ-2"


def test_successful_run_not_affected_by_failure_logic(synced_test_session: Session):
    """Test that successful critic+grader runs still work correctly (not affected by UNION ALL)."""
    snapshot_slug = SnapshotSlug("test-success-unaffected/2025-01-01-00")
    grader_agent_run_id = uuid4()

    files = ["test/file1.py"]

    snapshot = Snapshot(slug=snapshot_slug, split=Split.TRAIN, source=LocalSource(vcs="local", root="."))
    synced_test_session.add(snapshot)

    tp1 = TruePositive(
        snapshot_slug=snapshot_slug,
        tp_id="success-tp",
        rationale="Test issue",
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id="success-occ",
                files={Path("test/file1.py"): None},
                expect_caught_from={frozenset([Path("test/file1.py")])},
                note=None,
            )
        ],
    )
    synced_test_session.add(tp1)

    scope = ExplicitFileScope(files=files)
    example = Example.from_scope(snapshot_slug, scope)
    synced_test_session.add(example)

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

    # Create reported issue for this grader run
    make_reported_issues(agent_run_id=critic_run.agent_run_id, issue_ids=["input-1"], session=synced_test_session)

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
    tp = TruePositive(
        snapshot_slug=snapshot_slug,
        tp_id="or-logic-tp",
        rationale="Duplication - catchable from either file",
        occurrences=[
            TruePositiveOccurrence(
                occurrence_id="or-occ",
                files={Path("test/file1.py"): None, Path("test/file2.py"): None},
                expect_caught_from={
                    frozenset([Path("test/file1.py")]),  # OR
                    frozenset([Path("test/file2.py")]),  # OR
                },
                note=None,
            )
        ],
    )
    synced_test_session.add(tp)

    scope = ExplicitFileScope(files=files)
    example = Example.from_scope(snapshot_slug, scope)
    synced_test_session.add(example)

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
    snapshot_slug, scope_hash = factory.snapshot_slug, factory.scope_hash

    # Create 1 failed critic run (0 credit)
    factory.create_failed(AgentRunStatus.MAX_TURNS_EXCEEDED)

    # Create 1 successful critic run with 3 grader runs at different credits
    example = synced_test_session.query(Example).filter_by(snapshot_slug=snapshot_slug, scope_hash=scope_hash).one()
    create_critic_run_with_multiple_grader_runs(session=synced_test_session, example=example, credits=[0.5, 0.6, 0.7])

    synced_test_session.commit()

    # Query aggregated view using ORM (occurrence-based weighting)
    result = (
        synced_test_session.query(AggregatedRecallByDefinition)
        .filter_by(agent_definition_id=CRITIC_AGENT_DEFINITION_ID, split=Split.TRAIN, critic_model="test-model")
        .one()
    )

    assert result is not None, "Should have aggregated metrics"

    # Expected behavior (with correct weighting):
    # - 2 critic runs total: 1 successful, 1 max_turns_exceeded
    # - Failed run: avg_occurrences_caught = NULL, n_catchable_occurrences = 0 (no grader runs)
    # - Successful run: avg_occurrences_caught = avg(0.5, 0.6, 0.7) = 0.6, n_catchable_occurrences = 1
    # - avg_occurrences_caught_overall = AVG(0.0, 0.6) = 0.3
    # - avg_catchable_occurrences = AVG(0, 1) = 0.5
    # - recall = 0.3 / 0.5 = 0.6
    n_total_runs = result.n_successful + result.n_max_turns_exceeded + result.n_context_length_exceeded
    assert n_total_runs == 2, f"Should count both critic runs, got {n_total_runs}"
    assert result.n_successful == 1, "Should count 1 successful run"
    assert result.n_max_turns_exceeded == 1, "Should count 1 max_turns failure"

    # Check aggregated values
    assert abs(result.avg_occurrences_caught_overall - 0.3) < 0.01, (
        f"avg_occurrences_caught_overall should be 0.3, got {result.avg_occurrences_caught_overall}"
    )
    assert abs(float(result.avg_catchable_occurrences) - 0.5) < 0.01, (
        f"avg_catchable_occurrences should be 0.5, got {result.avg_catchable_occurrences}"
    )

    # Compute and check recall
    recall = result.avg_occurrences_caught_overall / float(result.avg_catchable_occurrences)
    assert abs(recall - 0.6) < 0.01, f"Recall should be 0.6 (0.3/0.5), got {recall}"

    # Without the fix, multiple grader runs would cause overweighting:
    # - Would incorrectly count 4 occurrence-runs (1 failed + 3 grader rows)
    # - Would compute recall as 0.45 instead of 0.3


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
        synced_test_session.query(AggregatedRecallByDefinition)
        .filter_by(agent_definition_id=CRITIC_AGENT_DEFINITION_ID, split=Split.TRAIN, critic_model="test-model")
        .one()
    )

    assert result is not None, "Should have aggregated metrics"
    n_total = result.n_successful + result.n_max_turns_exceeded + result.n_context_length_exceeded
    assert n_total == 6, f"Should count all 6 critic runs (3 success + 2 max_turns + 1 context), got {n_total}"
    assert result.n_successful == 3, "Should count 3 successful runs"
    assert result.n_max_turns_exceeded == 2, "Should count 2 max_turns_exceeded failures"
    assert result.n_context_length_exceeded == 1, "Should count 1 context_length_exceeded failure"


def test_aggregated_view_counts_zero_when_no_failures(synced_test_session: Session, critic_run_factory):
    """Test that failure counts are zero when all runs succeed."""
    factory = critic_run_factory(synced_test_session)

    # Create only successful runs
    for _i in range(3):
        factory.create_successful()

    synced_test_session.commit()

    # Query aggregated view using ORM (occurrence-based weighting)
    result = (
        synced_test_session.query(AggregatedRecallByDefinition)
        .filter_by(agent_definition_id=CRITIC_AGENT_DEFINITION_ID, split=Split.TRAIN, critic_model="test-model")
        .one()
    )

    assert result is not None, "Should have aggregated metrics"
    assert result.n_successful == 3, "Should count 3 successful runs"
    assert result.n_max_turns_exceeded == 0, "Should have zero max_turns failures"
    assert result.n_context_length_exceeded == 0, "Should have zero context_length failures"


def test_aggregated_recall_by_example_has_correct_weighting(synced_test_session: Session, critic_run_factory):
    """Test that aggregated_recall_by_example correctly weights critic runs (not grader runs)."""
    factory = critic_run_factory(synced_test_session)
    snapshot_slug = factory.snapshot_slug
    scope_hash = factory.scope_hash

    # Create 1 failed critic run
    factory.create_failed(AgentRunStatus.MAX_TURNS_EXCEEDED)

    # Create 1 successful critic run with 3 grader runs at different credits
    example = synced_test_session.query(Example).filter_by(snapshot_slug=snapshot_slug, scope_hash=scope_hash).one()
    create_critic_run_with_multiple_grader_runs(session=synced_test_session, example=example, credits=[0.4, 0.5, 0.6])

    synced_test_session.commit()

    # Query aggregated_recall_by_example using ORM (occurrence-based weighting)
    result = (
        synced_test_session.query(AggregatedRecallByExample)
        .filter_by(snapshot_slug=snapshot_slug, scope_hash=scope_hash)
        .one()
    )

    assert result is not None, "Should have example metrics"

    # Count critic runs
    n_total_runs = result.n_successful + result.n_max_turns_exceeded + result.n_context_length_exceeded
    assert n_total_runs == 2, f"Should count 2 critic runs, got {n_total_runs}"
    assert result.n_successful == 1, "Should count 1 successful run"
    assert result.n_max_turns_exceeded == 1, "Should count 1 max_turns failure"
    assert result.n_context_length_exceeded == 0, "Should count 0 context failures"

    # Occurrence-based weighting:
    # - Failed run: avg_occurrences_caught = NULL, n_catchable_occurrences = 0
    # - Successful run: avg_occurrences_caught = avg(0.4,0.5,0.6) = 0.5, n_catchable_occurrences = 1
    # - avg_occurrences_caught_overall = AVG(0.0, 0.5) = 0.25
    # - avg_catchable_occurrences = AVG(0, 1) = 0.5
    # - recall = 0.25 / 0.5 = 0.5
    assert abs(result.avg_occurrences_caught_overall - 0.25) < 0.01, (
        f"Expected 0.25, got {result.avg_occurrences_caught_overall}"
    )
    assert abs(float(result.avg_catchable_occurrences) - 0.5) < 0.01, (
        f"Expected 0.5, got {result.avg_catchable_occurrences}"
    )

    # Compute recall
    recall = result.avg_occurrences_caught_overall / float(result.avg_catchable_occurrences)
    assert abs(recall - 0.5) < 0.01, f"Expected recall 0.5 (0.25/0.5), got {recall}"


def test_occurrence_statistics_has_correct_n_critic_runs(synced_test_session: Session, basic_snapshot_with_tp):
    """Test that aggregated_recall_by_example counts critic runs correctly (not grader runs)."""
    snapshot_slug, scope_hash = basic_snapshot_with_tp(synced_test_session)

    # Get the example for critic run creation
    example = synced_test_session.query(Example).filter_by(snapshot_slug=snapshot_slug, scope_hash=scope_hash).one()

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
        synced_test_session.query(AggregatedRecallByExample)
        .filter_by(snapshot_slug=snapshot_slug, scope_hash=scope_hash)
        .one()
    )

    assert result is not None, "Should have aggregated stats for example"

    # Should count 2 critic runs, not 5 grader runs
    n_total_runs = result.n_successful + result.n_max_turns_exceeded + result.n_context_length_exceeded
    assert n_total_runs == 2, f"Should count 2 critic runs, got {n_total_runs}"
    assert result.n_successful == 2, "Should count 2 successful runs"

    # Occurrence-based weighting:
    # - Run 1: avg_occurrences_caught = 0.8 (1 grader)
    # - Run 2: avg_occurrences_caught = avg(0.5, 0.6, 0.7, 0.8) = 0.65 (4 graders averaged)
    # - avg_occurrences_caught_overall = (0.8 + 0.65) / 2 = 0.725
    # - avg_catchable_occurrences = 1 (one occurrence)
    # - recall = 0.725 / 1.0 = 0.725
    assert abs(result.avg_occurrences_caught_overall - 0.725) < 0.01, (
        f"Expected 0.725, got {result.avg_occurrences_caught_overall}"
    )
    assert abs(result.avg_catchable_occurrences - 1.0) < 0.01, f"Expected 1.0, got {result.avg_catchable_occurrences}"

    # Compute recall
    recall = result.avg_occurrences_caught_overall / float(result.avg_catchable_occurrences)
    assert abs(recall - 0.725) < 0.01, f"Expected recall 0.725, got {recall}"
