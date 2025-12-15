"""Test that failed critic runs appear in occurrence_credits view with zero credit."""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from adgn.props.critic.models import (
    CriticContextLengthExceeded,
    CriticMaxTurnsExceeded,
    CriticSubmitPayload,
    CriticSuccess,
)
from adgn.props.critic.persistence import critic_output_to_db, critic_submit_payload_to_db
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Critique, Example, GraderRun, Snapshot, TruePositive
from adgn.props.files_hash import hash_file_set
from adgn.props.grader.models import GraderSuccess, InputIssueID, OccurrenceMatch, OccurrenceResult, TruePositiveID
from adgn.props.grader.persistence import grader_success_to_db
from adgn.props.ids import SnapshotSlug
from adgn.props.models.snapshot import LocalSource
from adgn.props.models.true_positive import TruePositiveOccurrence
from adgn.props.rationale import Rationale
from tests.conftest import EMPTY_CANONICAL_ISSUES_SNAPSHOT


@pytest.fixture
def basic_snapshot_with_tp():
    """Fixture providing a snapshot with one TP occurrence."""
    snapshot_slug = SnapshotSlug(f"test-basic/{uuid4()}")
    files = ["test/file1.py"]
    files_hash = hash_file_set(files)

    def _create(session):
        snapshot = Snapshot(slug=snapshot_slug, split="train", source=LocalSource(vcs="local", root="."))
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

        example = Example.file_set(snapshot_slug=snapshot_slug, files=files)
        session.add(example)
        session.commit()

        return snapshot_slug, files, files_hash

    return _create


@dataclass
class CriticRunFactory:
    """Factory for creating critic runs in tests."""

    session: Session
    snapshot_slug: SnapshotSlug
    files: list[str]
    files_hash: str
    prompt_sha: str

    def create_successful(self):
        """Create a successful critic run with critique and grader run."""
        # Create critique
        critique_payload = CriticSubmitPayload(issues=[], notes_md=None)
        critique = Critique(snapshot_slug=self.snapshot_slug, payload=critic_submit_payload_to_db(critique_payload))
        self.session.add(critique)
        self.session.flush()

        # Create critic run
        critic_output = critic_output_to_db(CriticSuccess(result=critique_payload))
        critic_run = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=self.prompt_sha,
            snapshot_slug=self.snapshot_slug,
            model="test-model",
            critique_id=critique.id,
            files=self.files,
            files_hash=self.files_hash,
            output=critic_output,
        )
        self.session.add(critic_run)
        self.session.flush()

        # Create grader run with zero occurrences found
        grader_success = GraderSuccess(
            occurrence_results=[
                OccurrenceResult(
                    tp_id=TruePositiveID("test-tp-001"),
                    occurrence_id="occ-1",
                    found_credit=0.0,
                    matched_by=[],
                    rationale=Rationale("Occurrence not found in critique"),
                )
            ],
            unknowns=[],
            summary=Rationale("No issues found in critique"),
        )
        grader_run = GraderRun(
            transcript_id=uuid4(),
            snapshot_slug=self.snapshot_slug,
            model="test-grader-model",
            critique_id=critique.id,
            prompt_optimization_run_id=None,
            canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
            output=grader_success_to_db(grader_success),
        )
        self.session.add(grader_run)

    def create_failed(self, failure_type: str):
        """Create a failed critic run (max_turns or context_length)."""
        if failure_type == "max_turns":
            critic_output = critic_output_to_db(CriticMaxTurnsExceeded(max_turns=100))
        elif failure_type == "context_length":
            critic_output = critic_output_to_db(CriticContextLengthExceeded(error_message="Context limit exceeded"))
        else:
            raise ValueError(f"Unknown failure type: {failure_type}")

        critic_run = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=self.prompt_sha,
            snapshot_slug=self.snapshot_slug,
            model="test-model",
            critique_id=None,
            files=self.files,
            files_hash=self.files_hash,
            output=critic_output,
        )
        self.session.add(critic_run)


@pytest.fixture
def critic_run_factory(test_prompt_sha, basic_snapshot_with_tp):
    """Factory for creating critic runs with common parameters captured.

    Returns a factory function that takes a session and returns a CriticRunFactory.
    """

    def _make_factory(session):
        snapshot_slug, files, files_hash = basic_snapshot_with_tp(session)
        return CriticRunFactory(
            session=session, snapshot_slug=snapshot_slug, files=files, files_hash=files_hash, prompt_sha=test_prompt_sha
        )

    return _make_factory


def test_failed_critic_run_appears_with_zero_credit(test_db, test_prompt_sha):
    """Test that max_turns_exceeded critic runs generate zero-credit rows for catchable occurrences."""

    snapshot_slug = SnapshotSlug("test-failure/2025-01-01-00")
    critic_transcript_id = uuid4()

    # Files for the critic run
    files = ["test/file1.py"]
    files_hash = hash_file_set(files)

    with get_session() as session:
        # Insert snapshot
        snapshot = Snapshot(slug=snapshot_slug, split="train", source=LocalSource(vcs="local", root="."))
        session.add(snapshot)

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
        session.add(tp1)

        # Insert example (file-set)
        example = Example.file_set(snapshot_slug=snapshot_slug, files=files)
        session.add(example)

        # Insert failed critic run (max_turns_exceeded, no critique)
        critic_output_db = critic_output_to_db(CriticMaxTurnsExceeded(max_turns=100))
        critic_run = CriticRun(
            transcript_id=critic_transcript_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-critic-model",
            critique_id=None,  # No critique produced
            files=files,
            files_hash=files_hash,
            output=critic_output_db,
        )
        session.add(critic_run)
        session.commit()

        # Query occurrence_credits view - should include zero-credit row for the catchable occurrence
        result = session.execute(
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
        assert result.critic_run_id == critic_run.id, "Should reference the failed critic run"
        assert result.tp_id == "test-tp-001", "Should include the catchable TP"
        assert result.occurrence_id == "occ-1", "Should include the catchable occurrence"
        assert result.found_credit == 0.0, "Failed run should have zero credit"
        assert "max_turns_exceeded" in result.grader_rationale, "Rationale should mention failure reason"


def test_context_length_exceeded_also_counted_as_zero(test_db, test_prompt_sha):
    """Test that context_length_exceeded critic runs also generate zero-credit rows."""

    snapshot_slug = SnapshotSlug("test-context-failure/2025-01-01-00")
    critic_transcript_id = uuid4()

    files = ["test/file1.py"]
    files_hash = hash_file_set(files)

    with get_session() as session:
        snapshot = Snapshot(slug=snapshot_slug, split="train", source=LocalSource(vcs="local", root="."))
        session.add(snapshot)

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
        session.add(tp1)

        example = Example.file_set(snapshot_slug=snapshot_slug, files=files)
        session.add(example)

        # Insert failed critic run (context_length_exceeded)
        critic_output_db = critic_output_to_db(CriticContextLengthExceeded(error_message="Context limit exceeded"))
        critic_run = CriticRun(
            transcript_id=critic_transcript_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-critic-model",
            critique_id=None,
            files=files,
            files_hash=files_hash,
            output=critic_output_db,
        )
        session.add(critic_run)
        session.commit()

        result = session.execute(
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


def test_only_catchable_occurrences_included_for_failures(test_db, test_prompt_sha):
    """Test that failed runs only generate zero-credit rows for catchable occurrences."""

    snapshot_slug = SnapshotSlug("test-catchability/2025-01-01-00")
    critic_transcript_id = uuid4()

    # Review only file1.py
    files = ["test/file1.py"]
    files_hash = hash_file_set(files)

    with get_session() as session:
        snapshot = Snapshot(slug=snapshot_slug, split="train", source=LocalSource(vcs="local", root="."))
        session.add(snapshot)

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
        session.add(tp1)

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
        session.add(tp2)

        example = Example.file_set(snapshot_slug=snapshot_slug, files=files)
        session.add(example)

        critic_output_db = critic_output_to_db(CriticMaxTurnsExceeded(max_turns=100))
        critic_run = CriticRun(
            transcript_id=critic_transcript_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-critic-model",
            critique_id=None,
            files=files,
            files_hash=files_hash,
            output=critic_output_db,
        )
        session.add(critic_run)
        session.commit()

        # Should only see the catchable occurrence
        results = session.execute(
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


def test_whole_snapshot_failure_includes_all_occurrences(test_db, test_prompt_sha):
    """Test that whole-snapshot failed runs include all occurrences (no catchability filtering)."""

    snapshot_slug = SnapshotSlug("test-whole-snapshot-failure/2025-01-01-00")
    critic_transcript_id = uuid4()

    with get_session() as session:
        snapshot = Snapshot(slug=snapshot_slug, split="valid", source=LocalSource(vcs="local", root="."))
        session.add(snapshot)

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
        session.add(tp1)

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
        session.add(tp2)

        # Whole-snapshot example
        example = Example.whole_snapshot(snapshot_slug=snapshot_slug)
        session.add(example)

        # Failed critic run for whole-snapshot
        # CriticRun always stores actual files reviewed (never NULL)
        files = ["test/file1.py", "test/file2.py"]
        files_hash = hash_file_set(files)

        critic_output_db = critic_output_to_db(CriticMaxTurnsExceeded(max_turns=100))
        critic_run = CriticRun(
            transcript_id=critic_transcript_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-critic-model",
            critique_id=None,
            files=files,
            files_hash=files_hash,
            output=critic_output_db,
        )
        session.add(critic_run)
        session.commit()

        # Should include ALL occurrences (no catchability filtering for whole-snapshot)
        results = session.execute(
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


def test_successful_run_not_affected_by_failure_logic(test_db, test_prompt_sha):
    """Test that successful critic+grader runs still work correctly (not affected by UNION ALL)."""

    snapshot_slug = SnapshotSlug("test-success-unaffected/2025-01-01-00")
    critic_transcript_id = uuid4()
    grader_transcript_id = uuid4()
    critique_id = uuid4()

    files = ["test/file1.py"]
    files_hash = hash_file_set(files)

    with get_session() as session:
        snapshot = Snapshot(slug=snapshot_slug, split="train", source=LocalSource(vcs="local", root="."))
        session.add(snapshot)

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
        session.add(tp1)

        example = Example.file_set(snapshot_slug=snapshot_slug, files=files)
        session.add(example)

        # Successful critic run with critique
        critique_payload = CriticSubmitPayload(issues=[], notes_md=None)
        critique = Critique(
            id=critique_id, snapshot_slug=snapshot_slug, payload=critic_submit_payload_to_db(critique_payload)
        )
        session.add(critique)

        critic_output_db = critic_output_to_db(CriticSuccess(result=critique_payload))
        critic_run = CriticRun(
            transcript_id=critic_transcript_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-critic-model",
            critique_id=critique_id,
            files=files,
            files_hash=files_hash,
            output=critic_output_db,
        )
        session.add(critic_run)

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
            summary=Rationale("Test summary"),
        )

        grader_run = GraderRun(
            transcript_id=grader_transcript_id,
            snapshot_slug=snapshot_slug,
            critique_id=critique_id,
            model="test-grader-model",
            canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
            output=grader_success_to_db(grader_success),
        )
        session.add(grader_run)
        session.commit()

        # Should see the successful run with actual found_credit
        result = session.execute(
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


def test_multiple_occurrences_with_or_logic_in_expect_caught_from(test_db, test_prompt_sha):
    """Test catchability with OR logic: expect_caught_from with multiple trigger sets."""

    snapshot_slug = SnapshotSlug("test-or-logic/2025-01-01-00")
    critic_transcript_id = uuid4()

    # Review only file1.py
    files = ["test/file1.py"]
    files_hash = hash_file_set(files)

    with get_session() as session:
        snapshot = Snapshot(slug=snapshot_slug, split="train", source=LocalSource(vcs="local", root="."))
        session.add(snapshot)

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
        session.add(tp)

        example = Example.file_set(snapshot_slug=snapshot_slug, files=files)
        session.add(example)

        critic_output_db = critic_output_to_db(CriticMaxTurnsExceeded(max_turns=100))
        critic_run = CriticRun(
            transcript_id=critic_transcript_id,
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-critic-model",
            critique_id=None,
            files=files,
            files_hash=files_hash,
            output=critic_output_db,
        )
        session.add(critic_run)
        session.commit()

        # Should be catchable because file1.py satisfies one of the trigger sets
        result = session.execute(
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


def test_multiple_grader_runs_do_not_overweight_critic_run(test_db, critic_run_factory):
    """Test that multiple grader runs for same critic run don't cause overweighting.

    Regression test for weighting issue where a critic run graded N times
    would contribute N rows instead of 1 row (with averaged credit).
    """
    with get_session() as session:
        factory = critic_run_factory(session)
        snapshot_slug, files, files_hash = factory.snapshot_slug, factory.files, factory.files_hash

        # Create 1 failed critic run (0 credit)
        factory.create_failed("max_turns")

        # Create 1 successful critic run
        critique_payload = CriticSubmitPayload(issues=[], notes_md=None)
        critique = Critique(snapshot_slug=snapshot_slug, payload=critic_submit_payload_to_db(critique_payload))
        session.add(critique)
        session.flush()

        critic_output = critic_output_to_db(CriticSuccess(result=critique_payload))
        critic_run = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=factory.prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-model",
            critique_id=critique.id,
            files=files,
            files_hash=files_hash,
            output=critic_output,
        )
        session.add(critic_run)
        session.flush()

        # Grade the successful run 3 times with different credits
        for credit in [0.5, 0.6, 0.7]:
            grader_success = GraderSuccess(
                occurrence_results=[
                    OccurrenceResult(
                        tp_id=TruePositiveID("test-tp-001"),
                        occurrence_id="occ-1",
                        found_credit=credit,
                        matched_by=[],
                        rationale=Rationale(f"Found with credit {credit}"),
                    )
                ],
                unknowns=[],
                summary=Rationale(f"Graded with {credit}"),
            )
            grader_run = GraderRun(
                transcript_id=uuid4(),
                snapshot_slug=snapshot_slug,
                model="test-grader-model",
                critique_id=critique.id,
                prompt_optimization_run_id=None,
                canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
                output=grader_success_to_db(grader_success),
            )
            session.add(grader_run)

        session.commit()

        # Query aggregated view
        result = session.execute(
            text(
                """
                SELECT n_critic_runs, n_occurrences, total_credit, recall
                FROM aggregated_recall_by_prompt
                WHERE prompt_sha256 = :prompt_sha AND split = 'train'
            """
            ),
            {"prompt_sha": factory.prompt_sha},
        ).fetchone()

        assert result is not None, "Should have aggregated metrics"

        # Expected behavior (with correct weighting):
        # - 2 critic runs (1 failed, 1 successful)
        # - 2 occurrences (1 per critic run, not 4!)
        # - total_credit = 0.0 (failed) + avg(0.5, 0.6, 0.7) = 0.0 + 0.6 = 0.6
        # - recall = 0.6 / 2 = 0.3
        assert result.n_critic_runs == 2, "Should count both critic runs"
        assert result.n_occurrences == 2, "Should count 2 occurrences (1 per critic run), not 4"
        assert abs(result.total_credit - 0.6) < 0.01, f"Total credit should be 0.6, got {result.total_credit}"
        assert abs(result.recall - 0.3) < 0.01, f"Recall should be 0.3, got {result.recall}"

        # Without the fix, this would fail with:
        # - n_occurrences = 4 (1 failed + 3 successful grader rows)
        # - total_credit = 0.0 + 0.5 + 0.6 + 0.7 = 1.8
        # - recall = 1.8 / 4 = 0.45


def test_aggregated_view_counts_total_and_failed_runs(test_db, critic_run_factory):
    """Test that aggregated_recall_by_prompt includes n_critic_runs and failure counts."""
    with get_session() as session:
        factory = critic_run_factory(session)

        # Create 3 successful runs
        for _i in range(3):
            factory.create_successful()

        # Create 2 max_turns_exceeded failures
        for _i in range(2):
            factory.create_failed("max_turns")

        # Create 1 context_length_exceeded failure
        factory.create_failed("context_length")

        session.commit()

        # Query aggregated view
        result = session.execute(
            text(
                """
                SELECT n_critic_runs, n_max_turns_exceeded, n_context_length_exceeded
                FROM aggregated_recall_by_prompt
                WHERE prompt_sha256 = :prompt_sha AND split = 'train'
            """
            ),
            {"prompt_sha": factory.prompt_sha},
        ).fetchone()

        assert result is not None, "Should have aggregated metrics"
        assert result.n_critic_runs == 6, "Should count all 6 critic runs (3 success + 2 max_turns + 1 context)"
        assert result.n_max_turns_exceeded == 2, "Should count 2 max_turns_exceeded failures"
        assert result.n_context_length_exceeded == 1, "Should count 1 context_length_exceeded failure"


def test_aggregated_view_counts_zero_when_no_failures(test_db, critic_run_factory):
    """Test that failure counts are zero when all runs succeed."""
    with get_session() as session:
        factory = critic_run_factory(session)

        # Create only successful runs
        for _i in range(3):
            factory.create_successful()

        session.commit()

        # Query aggregated view
        result = session.execute(
            text(
                """
                SELECT n_critic_runs, n_max_turns_exceeded, n_context_length_exceeded
                FROM aggregated_recall_by_prompt
                WHERE prompt_sha256 = :prompt_sha AND split = 'train'
            """
            ),
            {"prompt_sha": factory.prompt_sha},
        ).fetchone()

        assert result is not None, "Should have aggregated metrics"
        assert result.n_critic_runs == 3, "Should count 3 successful runs"
        assert result.n_max_turns_exceeded == 0, "Should have zero max_turns failures"
        assert result.n_context_length_exceeded == 0, "Should have zero context_length failures"


def test_aggregated_recall_by_example_has_correct_weighting(test_db, critic_run_factory):
    """Test that aggregated_recall_by_example correctly weights critic runs (not grader runs)."""
    with get_session() as session:
        factory = critic_run_factory(session)
        snapshot_slug = factory.snapshot_slug
        files = factory.files
        files_hash = factory.files_hash

        # Create 1 failed critic run
        factory.create_failed("max_turns")

        # Create 1 successful critic run graded 3 times
        critique_payload = CriticSubmitPayload(issues=[], notes_md=None)
        critique = Critique(snapshot_slug=snapshot_slug, payload=critic_submit_payload_to_db(critique_payload))
        session.add(critique)
        session.flush()

        critic_output = critic_output_to_db(CriticSuccess(result=critique_payload))
        critic_run = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=factory.prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-model",
            critique_id=critique.id,
            files=files,
            files_hash=files_hash,
            output=critic_output,
        )
        session.add(critic_run)
        session.flush()

        # Grade 3 times with different credits
        for credit in [0.4, 0.5, 0.6]:
            grader_success = GraderSuccess(
                occurrence_results=[
                    OccurrenceResult(
                        tp_id=TruePositiveID("test-tp-001"),
                        occurrence_id="occ-1",
                        found_credit=credit,
                        matched_by=[],
                        rationale=Rationale(f"Credit {credit}"),
                    )
                ],
                unknowns=[],
                summary=Rationale(f"Summary {credit}"),
            )
            grader_run = GraderRun(
                transcript_id=uuid4(),
                snapshot_slug=snapshot_slug,
                model="test-grader-model",
                critique_id=critique.id,
                prompt_optimization_run_id=None,
                canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
                output=grader_success_to_db(grader_success),
            )
            session.add(grader_run)

        session.commit()

        # Query aggregated_recall_by_example
        result = session.execute(
            text(
                """
                SELECT n_critic_runs, n_occurrences, total_credit, recall,
                       n_max_turns_exceeded, n_context_length_exceeded
                FROM aggregated_recall_by_example
                WHERE snapshot_slug = :slug AND files_hash = :hash AND split = 'train'
            """
            ),
            {"slug": str(snapshot_slug), "hash": files_hash},
        ).fetchone()

        assert result is not None, "Should have example metrics"
        assert result.n_critic_runs == 2, "Should count 2 critic runs"
        assert result.n_occurrences == 2, "Should count 2 occurrences (1 per critic run)"
        # total_credit = 0.0 (failed) + avg(0.4, 0.5, 0.6) = 0.5
        assert abs(result.total_credit - 0.5) < 0.01, f"Expected 0.5, got {result.total_credit}"
        assert abs(result.recall - 0.25) < 0.01, f"Expected 0.25 (0.5/2), got {result.recall}"
        assert result.n_max_turns_exceeded == 1, "Should count 1 max_turns failure"
        assert result.n_context_length_exceeded == 0, "Should count 0 context failures"


def test_occurrence_statistics_has_correct_n_critic_runs(test_db, test_prompt_sha, basic_snapshot_with_tp):
    """Test that occurrence_statistics.n_critic_runs counts critic runs, not grader runs."""
    with get_session() as session:
        snapshot_slug, files, files_hash = basic_snapshot_with_tp(session)

        # Create 2 critic runs with different numbers of grader runs
        # Critic run 1: graded 1 time (credit 0.8)
        critique1 = Critique(
            snapshot_slug=snapshot_slug,
            payload=critic_submit_payload_to_db(CriticSubmitPayload(issues=[], notes_md=None)),
        )
        session.add(critique1)
        session.flush()

        critic_run1 = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-model",
            critique_id=critique1.id,
            files=files,
            files_hash=files_hash,
            output=critic_output_to_db(CriticSuccess(result=CriticSubmitPayload(issues=[], notes_md=None))),
        )
        session.add(critic_run1)
        session.flush()

        grader_run1 = GraderRun(
            transcript_id=uuid4(),
            snapshot_slug=snapshot_slug,
            model="test-grader-model",
            critique_id=critique1.id,
            prompt_optimization_run_id=None,
            canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
            output=grader_success_to_db(
                GraderSuccess(
                    occurrence_results=[
                        OccurrenceResult(
                            tp_id=TruePositiveID("test-tp-001"),
                            occurrence_id="occ-1",
                            found_credit=0.8,
                            matched_by=[],
                            rationale=Rationale("Found in critique"),
                        )
                    ],
                    unknowns=[],
                    summary=Rationale("Grader summary"),
                )
            ),
        )
        session.add(grader_run1)

        # Critic run 2: graded 4 times (credits 0.5, 0.6, 0.7, 0.8)
        critique2 = Critique(
            snapshot_slug=snapshot_slug,
            payload=critic_submit_payload_to_db(CriticSubmitPayload(issues=[], notes_md=None)),
        )
        session.add(critique2)
        session.flush()

        critic_run2 = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=test_prompt_sha,
            snapshot_slug=snapshot_slug,
            model="test-model",
            critique_id=critique2.id,
            files=files,
            files_hash=files_hash,
            output=critic_output_to_db(CriticSuccess(result=CriticSubmitPayload(issues=[], notes_md=None))),
        )
        session.add(critic_run2)
        session.flush()

        for credit in [0.5, 0.6, 0.7, 0.8]:
            grader_run = GraderRun(
                transcript_id=uuid4(),
                snapshot_slug=snapshot_slug,
                model="test-grader-model",
                critique_id=critique2.id,
                prompt_optimization_run_id=None,
                canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
                output=grader_success_to_db(
                    GraderSuccess(
                        occurrence_results=[
                            OccurrenceResult(
                                tp_id=TruePositiveID("test-tp-001"),
                                occurrence_id="occ-1",
                                found_credit=credit,
                                matched_by=[],
                                rationale=Rationale(f"Credit {credit}"),
                            )
                        ],
                        unknowns=[],
                        summary=Rationale(f"Summary {credit}"),
                    )
                ),
            )
            session.add(grader_run)

        session.commit()

        # Query occurrence_statistics
        result = session.execute(
            text(
                """
                SELECT n_critic_runs, mean_credit, min_credit, max_credit
                FROM occurrence_statistics
                WHERE tp_id = 'test-tp-001' AND occurrence_id = 'occ-1' AND split = 'train'
            """
            )
        ).fetchone()

        assert result is not None, "Should have occurrence statistics"
        # Should count 2 critic runs, not 5 grader runs
        assert result.n_critic_runs == 2, f"Should count 2 critic runs, got {result.n_critic_runs}"
        # mean_credit = avg(0.8, avg(0.5,0.6,0.7,0.8)) = avg(0.8, 0.65) = 0.725
        assert abs(result.mean_credit - 0.725) < 0.01, f"Expected 0.725, got {result.mean_credit}"
        # min = min(0.8, avg(0.5,0.6,0.7,0.8)) = min(0.8, 0.65) = 0.65
        assert abs(result.min_credit - 0.65) < 0.01, f"Expected 0.65, got {result.min_credit}"
        # max = max(0.8, avg(0.5,0.6,0.7,0.8)) = max(0.8, 0.65) = 0.8
        assert abs(result.max_credit - 0.8) < 0.01, f"Expected 0.8, got {result.max_credit}"
