"""Test grader submission validation - ensures grader must grade every TP occurrence in scope.

Tests for validation enforced by GraderSubmitServer.submit_result() tool.
"""

from pathlib import Path

from fastmcp.exceptions import ToolError
import pytest
import pytest_asyncio
from sqlalchemy.orm import joinedload

from adgn.props.critic.persistence import convert_reported_occurrence_orm_to_mcp
from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.db.models import CriticRun, CriticRunStatus, ReportedIssue, Snapshot, TruePositive
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.grader.grader import (
    GRADER_CANONICAL_TPS_RESOURCE_URI,
    GRADER_CRITIQUE_ISSUES_RESOURCE_URI,
    GRADER_KNOWN_FPS_RESOURCE_URI,
    GRADER_SNAPSHOT_SLUG_RESOURCE_URI,
    GradeInputs,
    GraderSubmitServer,
    GradeSubmitState,
)
from adgn.props.grader.models import (
    CritiqueInputIssue,
    FalsePositiveID,
    InputIssueID,
    KnownFalsePositive,
    OccurrenceMatch,
    OccurrenceResult,
    TruePositiveID,
    TruePositiveIssue,
    UnknownIssue,
)
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import CriticScopeSpec, ExplicitFileScope
from adgn.props.rationale import Rationale
from tests.props.conftest import make_critic_run, make_tp_occurrence

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def test_snapshot_with_tps(synced_test_fixtures):
    """Create snapshot with 3 TPs (4 total occurrences) for testing.

    Uses test-trivial git fixture but adds synthetic TPs with known IDs
    for validation testing.
    """
    with get_session() as session:
        # Get test-trivial snapshot from git fixtures
        snapshot = session.query(Snapshot).filter_by(slug="test-fixtures/test-trivial").one()

        # Clear existing TPs from git fixture (we need specific structure for validation tests)
        session.query(TruePositive).filter_by(snapshot_slug=snapshot.slug).delete()

        # TP 1: Single occurrence in file1.py
        tp1 = TruePositive(
            snapshot_slug=snapshot.slug,
            tp_id="tp-001",
            rationale="Dead code in file1",
            occurrences=[
                make_tp_occurrence(
                    occurrence_id="occ-001",
                    files={Path("file1.py"): None},
                    expect_caught_from={frozenset([Path("file1.py")])},
                )
            ],
        )
        session.add(tp1)

        # TP 2: Two occurrences in file2.py and file3.py (duplication pattern)
        tp2 = TruePositive(
            snapshot_slug=snapshot.slug,
            tp_id="tp-002",
            rationale="Duplicated logic across files",
            occurrences=[
                make_tp_occurrence(
                    occurrence_id="occ-002-a",
                    files={Path("file2.py"): None},
                    expect_caught_from={
                        frozenset([Path("file2.py")]),
                        frozenset([Path("file3.py")]),
                    },  # Either file triggers detection
                ),
                make_tp_occurrence(
                    occurrence_id="occ-002-b",
                    files={Path("file3.py"): None},
                    expect_caught_from={
                        frozenset([Path("file2.py")]),
                        frozenset([Path("file3.py")]),
                    },  # Either file triggers detection
                ),
            ],
        )
        session.add(tp2)

        # TP 3: Single occurrence in file4.py
        tp3 = TruePositive(
            snapshot_slug=snapshot.slug,
            tp_id="tp-003",
            rationale="Type error in file4",
            occurrences=[
                make_tp_occurrence(
                    occurrence_id="occ-003",
                    files={Path("file4.py"): None},
                    expect_caught_from={frozenset([Path("file4.py")])},
                )
            ],
        )
        session.add(tp3)

        session.commit()

        # Get slug before exiting session context
        return snapshot.slug


@pytest.fixture
def critic_run_with_3_issues(synced_test_fixtures, test_snapshot_with_tps, all_files_scope):
    """Create critic run with 3 reported issues in normalized tables."""
    with get_session() as session:
        # Get or create Example (git fixtures may have already created it)
        example = Example.from_scope(test_snapshot_with_tps, all_files_scope)
        existing = (
            session.query(Example).filter_by(snapshot_slug=example.snapshot_slug, scope_hash=example.scope_hash).first()
        )
        if existing:
            example = existing
        else:
            session.add(example)
            session.flush()

        prompt_sha256 = hash_and_upsert_prompt("test prompt for validation test")

        # Create critic run with empty JSONB (normalized tables are source of truth)
        critic_run = make_critic_run(example=example, prompt_sha256=prompt_sha256, status=CriticRunStatus.COMPLETED)
        session.add(critic_run)
        session.flush()  # Get critic_run.id

        # Create issues in normalized tables
        issues_orm = [
            ReportedIssue(critic_run_id=critic_run.id, issue_id="input-001", rationale="Found dead code"),
            ReportedIssue(critic_run_id=critic_run.id, issue_id="input-002", rationale="Found duplication"),
            ReportedIssue(critic_run_id=critic_run.id, issue_id="input-003", rationale="Found type error"),
        ]
        session.add_all(issues_orm)
        session.commit()
        return critic_run.id


# =============================================================================
# Tests: Missing TP Occurrences
# =============================================================================


def _make_grader_submit_server(snapshot_slug: str, critic_run_id, scope: CriticScopeSpec) -> GraderSubmitServer:
    """Helper to create GraderSubmitServer with specified file scope.

    Args:
        snapshot_slug: Snapshot slug
        critic_run_id: CriticRun ID
        scope: Critic scope (ExplicitFileScope | AllFilesScope)

    Returns:
        GraderSubmitServer instance
    """
    with get_session() as session:
        # Eagerly load relationships to avoid DetachedInstanceError
        snapshot_orm = (
            session.query(Snapshot)
            .filter_by(slug=snapshot_slug)
            .options(joinedload(Snapshot.true_positives), joinedload(Snapshot.false_positives))
            .one()
        )
        critic_run = (
            session.query(CriticRun)
            .options(joinedload(CriticRun.reported_issues).joinedload(ReportedIssue.occurrences))
            .get(critic_run_id)
        )
        assert critic_run is not None, f"CriticRun {critic_run_id} not found"
        assert critic_run.status == CriticRunStatus.COMPLETED, "Expected completed critic run"

        # Load ground truth data for resources
        canonical_tps = [
            TruePositiveIssue(
                id=TruePositiveID(tp.tp_id), rationale=Rationale(tp.rationale), occurrences=tp.occurrences
            )
            for tp in snapshot_orm.true_positives
        ]

        canonical_fps = [
            KnownFalsePositive(
                id=FalsePositiveID(fp.fp_id), rationale=Rationale(fp.rationale), occurrences=fp.occurrences
            )
            for fp in snapshot_orm.false_positives
        ]

        # Build critique_typed directly from ORM reported issues
        critique_typed = [
            CritiqueInputIssue(
                id=InputIssueID(issue.issue_id),
                rationale=Rationale(issue.rationale),
                occurrences=[convert_reported_occurrence_orm_to_mcp(occ) for occ in issue.occurrences],
            )
            for issue in critic_run.reported_issues
        ]

    inputs = GradeInputs(
        snapshot_slug=SnapshotSlug(snapshot_slug),
        canonical_tps=canonical_tps,
        critique_typed=critique_typed,
        canonical_fps=canonical_fps,
        scope=scope,
    )

    state = GradeSubmitState()
    # Generate a test grader_run_id (required for submit server)
    from uuid import uuid4

    grader_run_id = uuid4()
    return GraderSubmitServer(state, inputs, grader_run_id, auth=None)


@pytest_asyncio.fixture
async def grader_all_files(synced_test_fixtures, test_snapshot_with_tps, critic_run_with_3_issues, all_files_scope):
    """Create GraderSubmitServer with all files in scope (4 expected occurrences)."""
    return _make_grader_submit_server(test_snapshot_with_tps, critic_run_with_3_issues, scope=all_files_scope)


async def test_submit_refuses_missing_one_occurrence(grader_all_files):
    """Grader must grade every TP occurrence - reject if one is missing."""

    # Submit results for only 3 out of 4 expected occurrences (missing occ-002-b)
    occurrence_results = [
        OccurrenceResult(
            tp_id=TruePositiveID("tp-001"),
            occurrence_id="occ-001",
            found_credit=0.8,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-001"), credit=0.8)],
            rationale=Rationale("Matched to input-001"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-002"),
            occurrence_id="occ-002-a",  # Only first occurrence of tp-002
            found_credit=0.9,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-002"), credit=0.9)],
            rationale=Rationale("Matched to input-002"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-003"),
            occurrence_id="occ-003",
            found_credit=1.0,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-003"), credit=1.0)],
            rationale=Rationale("Matched to input-003"),
        ),
        # Missing: tp-002/occ-002-b
    ]

    # Should raise ToolError about missing occurrence
    with pytest.raises(ToolError) as exc_info:
        await grader_all_files.submit_result_tool.fn(
            occurrence_results=occurrence_results, unknowns=[], summary=Rationale("Test grading")
        )

    error_message = str(exc_info.value)
    assert "Missing grading results for 1 TP occurrence(s)" in error_message
    assert "tp-002/occ-002-b" in error_message


async def test_submit_refuses_missing_all_occurrences(grader_all_files):
    """Grader must grade every TP occurrence - reject if all are missing."""

    # Submit empty results (no occurrences graded)
    unknowns = [
        UnknownIssue(input_id=InputIssueID("input-001"), rationale=Rationale("Novel issue found in code")),
        UnknownIssue(input_id=InputIssueID("input-002"), rationale=Rationale("Another novel issue")),
        UnknownIssue(input_id=InputIssueID("input-003"), rationale=Rationale("Third novel issue")),
    ]

    # Should raise ToolError about missing all 4 occurrences
    with pytest.raises(ToolError) as exc_info:
        await grader_all_files.submit_result_tool.fn(
            occurrence_results=[], unknowns=unknowns, summary=Rationale("All unknowns, no TPs matched")
        )

    error_message = str(exc_info.value)
    assert "Missing grading results for 4 TP occurrence(s)" in error_message
    # Check for presence of at least some occurrence IDs
    assert "occ-001" in error_message or "occ-002" in error_message


async def test_submit_accepts_all_occurrences_graded(grader_all_files):
    """Grader accepts submission when all TP occurrences are graded."""

    # Submit results for all 4 expected occurrences
    occurrence_results = [
        OccurrenceResult(
            tp_id=TruePositiveID("tp-001"),
            occurrence_id="occ-001",
            found_credit=0.8,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-001"), credit=0.8)],
            rationale=Rationale("Matched to input-001"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-002"),
            occurrence_id="occ-002-a",
            found_credit=0.9,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-002"), credit=0.9)],
            rationale=Rationale("Matched to input-002 (first occurrence)"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-002"),
            occurrence_id="occ-002-b",  # Second occurrence of tp-002
            found_credit=0.9,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-002"), credit=0.9)],
            rationale=Rationale("Matched to input-002 (second occurrence)"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-003"),
            occurrence_id="occ-003",
            found_credit=1.0,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-003"), credit=1.0)],
            rationale=Rationale("Matched to input-003"),
        ),
    ]

    # Should succeed
    result = await grader_all_files.submit_result_tool.fn(
        occurrence_results=occurrence_results, unknowns=[], summary=Rationale("Complete grading")
    )
    assert result.ok is True


# =============================================================================
# Tests: Scoped Validation (reviewed_files filter)
# =============================================================================


@pytest_asyncio.fixture
async def grader_file1_only(synced_test_fixtures, test_snapshot_with_tps, critic_run_with_3_issues):
    """Create GraderSubmitServer with only file1.py in scope (1 expected occurrence)."""
    # Only file1.py reviewed = only tp-001/occ-001 is catchable
    return _make_grader_submit_server(
        test_snapshot_with_tps, critic_run_with_3_issues, scope=ExplicitFileScope(files=["file1.py"])
    )


async def test_submit_scoped_validation_accepts_only_catchable(grader_file1_only):
    """With scoped validation, only catchable occurrences must be graded."""

    # Only need to grade tp-001/occ-001 (the only catchable occurrence from file1.py)
    occurrence_results = [
        OccurrenceResult(
            tp_id=TruePositiveID("tp-001"),
            occurrence_id="occ-001",
            found_credit=1.0,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-001"), credit=1.0)],
            rationale=Rationale("Found in file1.py"),
        )
    ]
    unknowns = [
        UnknownIssue(input_id=InputIssueID("input-002"), rationale=Rationale("Novel finding here")),
        UnknownIssue(input_id=InputIssueID("input-003"), rationale=Rationale("Another novel finding")),
    ]

    # Should succeed (only graded the catchable occurrence)
    result = await grader_file1_only.submit_result_tool.fn(
        occurrence_results=occurrence_results, unknowns=unknowns, summary=Rationale("Scoped grading (file1.py only)")
    )
    assert result.ok is True


async def test_submit_scoped_validation_refuses_out_of_scope(grader_file1_only):
    """With scoped validation, cannot grade occurrences not in scope."""

    # Try to grade an occurrence not catchable from file1.py
    occurrence_results = [
        OccurrenceResult(
            tp_id=TruePositiveID("tp-001"),
            occurrence_id="occ-001",
            found_credit=1.0,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-001"), credit=1.0)],
            rationale=Rationale("Found in file1.py"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-002"),
            occurrence_id="occ-002-a",  # NOT catchable from file1.py
            found_credit=0.5,
            matched_by=[],
            rationale=Rationale("Should not be in scope here"),
        ),
    ]
    unknowns = [
        UnknownIssue(input_id=InputIssueID("input-002"), rationale=Rationale("Novel finding A")),
        UnknownIssue(input_id=InputIssueID("input-003"), rationale=Rationale("Novel finding B")),
    ]

    # Should raise ToolError about unexpected occurrence
    with pytest.raises(ToolError) as exc_info:
        await grader_file1_only.submit_result_tool.fn(
            occurrence_results=occurrence_results, unknowns=unknowns, summary=Rationale("Invalid submission")
        )

    error_message = str(exc_info.value)
    assert "Unexpected TP occurrence(s) not in scope" in error_message
    assert "tp-002/occ-002-a" in error_message


# =============================================================================
# Tests: Input Critique Validation (existing validation)
# =============================================================================


async def test_submit_refuses_unaccounted_input_issue(grader_all_files):
    """Every critique issue must be matched to TPs or marked as unknown."""

    # Submit results but don't account for input-003
    occurrence_results = [
        OccurrenceResult(
            tp_id=TruePositiveID("tp-001"),
            occurrence_id="occ-001",
            found_credit=0.8,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-001"), credit=0.8)],
            rationale=Rationale("Matched occurrence in file"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-002"),
            occurrence_id="occ-002-a",
            found_credit=0.0,
            matched_by=[],
            rationale=Rationale("Not matched to any input"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-002"),
            occurrence_id="occ-002-b",
            found_credit=0.0,
            matched_by=[],
            rationale=Rationale("Also not matched"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-003"),
            occurrence_id="occ-003",
            found_credit=0.0,
            matched_by=[],
            rationale=Rationale("Not matched either"),
        ),
    ]
    unknowns = [
        UnknownIssue(input_id=InputIssueID("input-002"), rationale=Rationale("Novel issue found"))
        # Missing: input-003 (not in matched_by and not in unknowns)
    ]

    # Should raise ToolError about unaccounted input issue
    with pytest.raises(ToolError) as exc_info:
        await grader_all_files.submit_result_tool.fn(
            occurrence_results=occurrence_results,
            unknowns=unknowns,
            summary=Rationale("Incomplete accounting of inputs"),
        )

    error_message = str(exc_info.value)
    assert "Input critique issues not accounted for" in error_message
    assert "input-003" in error_message


async def test_submit_refuses_invalid_unknown_id(grader_all_files):
    """Unknown issue IDs must come from the input critique."""

    # Try to submit unknown with invalid ID
    occurrence_results = [
        OccurrenceResult(
            tp_id=TruePositiveID("tp-001"),
            occurrence_id="occ-001",
            found_credit=1.0,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-001"), credit=1.0)],
            rationale=Rationale("Matched occurrence here"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-002"),
            occurrence_id="occ-002-a",
            found_credit=1.0,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-002"), credit=1.0)],
            rationale=Rationale("Matched occurrence there"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-002"),
            occurrence_id="occ-002-b",
            found_credit=1.0,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-002"), credit=1.0)],
            rationale=Rationale("Matched occurrence again"),
        ),
        OccurrenceResult(
            tp_id=TruePositiveID("tp-003"),
            occurrence_id="occ-003",
            found_credit=1.0,
            matched_by=[OccurrenceMatch(input_id=InputIssueID("input-003"), credit=1.0)],
            rationale=Rationale("Matched final occurrence"),
        ),
    ]
    unknowns = [
        UnknownIssue(
            input_id=InputIssueID("invalid-999"), rationale=Rationale("Fake unknown issue here")
        )  # Not from input critique
    ]

    # Should raise ToolError about invalid unknown ID
    with pytest.raises(ToolError) as exc_info:
        await grader_all_files.submit_result_tool.fn(
            occurrence_results=occurrence_results, unknowns=unknowns, summary=Rationale("Invalid unknown ID test")
        )

    error_message = str(exc_info.value)
    assert "Unknown issue IDs not from input critique" in error_message
    assert "invalid-999" in error_message


# =============================================================================
# Tests: Ground Truth Resources
# =============================================================================


async def test_grader_resources_available(grader_all_files):
    """GraderSubmitServer exposes ground truth as MCP resources."""

    # Verify resource attributes exist
    assert grader_all_files.snapshot_slug_resource is not None
    assert grader_all_files.canonical_tps_resource is not None
    assert grader_all_files.critique_issues_resource is not None
    assert grader_all_files.known_fps_resource is not None

    # Verify resource URIs match constants (compare as strings)
    assert str(grader_all_files.snapshot_slug_resource.uri) == GRADER_SNAPSHOT_SLUG_RESOURCE_URI
    assert str(grader_all_files.canonical_tps_resource.uri) == GRADER_CANONICAL_TPS_RESOURCE_URI
    assert str(grader_all_files.critique_issues_resource.uri) == GRADER_CRITIQUE_ISSUES_RESOURCE_URI
    assert str(grader_all_files.known_fps_resource.uri) == GRADER_KNOWN_FPS_RESOURCE_URI


async def test_grader_resources_return_data(grader_all_files):
    """Ground truth resources return expected data types."""

    # Call resource functions directly
    snapshot_slug = await grader_all_files.snapshot_slug_resource.fn()
    canonical_tps = await grader_all_files.canonical_tps_resource.fn()
    critique_issues = await grader_all_files.critique_issues_resource.fn()
    known_fps = await grader_all_files.known_fps_resource.fn()

    # Verify snapshot_slug is string
    assert isinstance(snapshot_slug, str)
    assert snapshot_slug == "test-fixtures/test-trivial"

    # Verify canonical_tps is list
    assert isinstance(canonical_tps, list)
    assert len(canonical_tps) == 3  # 3 TPs in test fixture
    # Verify structure (should be TruePositiveIssue instances)
    assert all(hasattr(tp, "id") and hasattr(tp, "rationale") and hasattr(tp, "occurrences") for tp in canonical_tps)

    # Verify critique_issues is list
    assert isinstance(critique_issues, list)
    assert len(critique_issues) == 3  # 3 issues in test fixture
    # Verify structure (should be CritiqueInputIssue instances)
    assert all(hasattr(issue, "id") and hasattr(issue, "rationale") for issue in critique_issues)

    # Verify known_fps is list (may be empty)
    assert isinstance(known_fps, list)
