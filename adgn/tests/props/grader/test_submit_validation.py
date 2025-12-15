"""Test grader submission validation - ensures grader must grade every TP occurrence in scope.

Tests for validation enforced by GraderSubmitServer.submit_result() tool.
"""

from pathlib import Path

from fastmcp.exceptions import ToolError
import pytest
import pytest_asyncio

from adgn.props.critic.models import ReportedIssue
from adgn.props.db import get_session
from adgn.props.db.models import Critique, Snapshot
from adgn.props.grader.grader import GradeInputs, GraderSubmitServer, GradeSubmitState
from adgn.props.grader.models import (
    GradeValidationContext,
    InputIssueID,
    OccurrenceMatch,
    OccurrenceResult,
    TruePositiveID,
    UnknownIssue,
)
from adgn.props.ids import SnapshotSlug
from adgn.props.rationale import Rationale
from tests.props.conftest import make_critique, make_test_snapshot, make_tp_occurrence, make_true_positive

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def test_snapshot_with_tps(test_db):
    """Create snapshot with 3 TPs (4 total occurrences) for testing."""
    with get_session() as session:
        # Snapshot with 3 TPs
        snapshot = make_test_snapshot("test/validation")
        session.add(snapshot)

        # TP 1: Single occurrence in file1.py
        tp1 = make_true_positive(
            "test/validation",
            tp_id="tp-001",
            rationale="Dead code in file1",
            occurrences=[
                make_tp_occurrence(occurrence_id="occ-001", files={"file1.py": None}, expect_caught_from=[["file1.py"]])
            ],
        )
        session.add(tp1)

        # TP 2: Two occurrences in file2.py and file3.py (duplication pattern)
        tp2 = make_true_positive(
            "test/validation",
            tp_id="tp-002",
            rationale="Duplicated logic across files",
            occurrences=[
                make_tp_occurrence(
                    occurrence_id="occ-002-a",
                    files={"file2.py": None},
                    expect_caught_from=[["file2.py"], ["file3.py"]],  # Either file triggers detection
                ),
                make_tp_occurrence(
                    occurrence_id="occ-002-b",
                    files={"file3.py": None},
                    expect_caught_from=[["file2.py"], ["file3.py"]],  # Either file triggers detection
                ),
            ],
        )
        session.add(tp2)

        # TP 3: Single occurrence in file4.py
        tp3 = make_true_positive(
            "test/validation",
            tp_id="tp-003",
            rationale="Type error in file4",
            occurrences=[
                make_tp_occurrence(occurrence_id="occ-003", files={"file4.py": None}, expect_caught_from=[["file4.py"]])
            ],
        )
        session.add(tp3)

        session.commit()

    return "test/validation"


@pytest.fixture
def critique_with_3_issues(test_db, test_snapshot_with_tps):
    """Create critique with 3 reported issues."""
    with get_session() as session:
        critique = make_critique(
            test_snapshot_with_tps,
            issues=[
                ReportedIssue(id="input-001", rationale=Rationale("Found dead code"), occurrences=[]),
                ReportedIssue(id="input-002", rationale=Rationale("Found duplication"), occurrences=[]),
                ReportedIssue(id="input-003", rationale=Rationale("Found type error"), occurrences=[]),
            ],
        )
        session.add(critique)
        session.commit()
        return critique.id


# =============================================================================
# Tests: Missing TP Occurrences
# =============================================================================


def _make_grader_submit_server(
    snapshot_slug: str, critique_id, reviewed_files: set[Path] | None
) -> tuple[GraderSubmitServer, GradeValidationContext]:
    """Helper to create GraderSubmitServer with specified file scope.

    Args:
        snapshot_slug: Snapshot slug
        critique_id: Critique ID
        reviewed_files: Files in scope (None = all files)

    Returns:
        Tuple of (GraderSubmitServer, GradeValidationContext)
    """
    with get_session() as session:
        snapshot_orm = session.query(Snapshot).filter_by(slug=snapshot_slug).one()
        critique = session.query(Critique).get(critique_id)
        assert critique is not None, f"Critique {critique_id} not found"

        # Eagerly load payload to avoid DetachedInstanceError
        critique_payload = critique.payload

        # Create validation context with specified file scope
        context = GradeValidationContext.from_specimen_and_critique(
            snapshot_orm, critique_payload, reviewed_files=reviewed_files
        )

    inputs = GradeInputs(
        snapshot_slug=SnapshotSlug(snapshot_slug), critique=critique_payload, reviewed_files=reviewed_files
    )

    state = GradeSubmitState()
    return GraderSubmitServer(state, inputs, auth=None), context


@pytest_asyncio.fixture
async def grader_submit_server_all_files(test_db, test_snapshot_with_tps, critique_with_3_issues):
    """Create GraderSubmitServer with all files in scope (4 expected occurrences)."""
    return _make_grader_submit_server(test_snapshot_with_tps, critique_with_3_issues, reviewed_files=None)


async def test_submit_refuses_missing_one_occurrence(grader_submit_server_all_files):
    """Grader must grade every TP occurrence - reject if one is missing."""
    server, context = grader_submit_server_all_files

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
        await server.submit_result_tool.fn(
            occurrence_results=occurrence_results, unknowns=[], summary=Rationale("Test grading")
        )

    error_message = str(exc_info.value)
    assert "Missing grading results for 1 TP occurrence(s)" in error_message
    assert "tp-002/occ-002-b" in error_message


async def test_submit_refuses_missing_all_occurrences(grader_submit_server_all_files):
    """Grader must grade every TP occurrence - reject if all are missing."""
    server, context = grader_submit_server_all_files

    # Submit empty results (no occurrences graded)
    unknowns = [
        UnknownIssue(input_id=InputIssueID("input-001"), rationale=Rationale("Novel issue found in code")),
        UnknownIssue(input_id=InputIssueID("input-002"), rationale=Rationale("Another novel issue")),
        UnknownIssue(input_id=InputIssueID("input-003"), rationale=Rationale("Third novel issue")),
    ]

    # Should raise ToolError about missing all 4 occurrences
    with pytest.raises(ToolError) as exc_info:
        await server.submit_result_tool.fn(
            occurrence_results=[], unknowns=unknowns, summary=Rationale("All unknowns, no TPs matched")
        )

    error_message = str(exc_info.value)
    assert "Missing grading results for 4 TP occurrence(s)" in error_message
    # Check for presence of at least some occurrence IDs
    assert "occ-001" in error_message or "occ-002" in error_message


async def test_submit_accepts_all_occurrences_graded(grader_submit_server_all_files):
    """Grader accepts submission when all TP occurrences are graded."""
    server, context = grader_submit_server_all_files

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
    result = await server.submit_result_tool.fn(
        occurrence_results=occurrence_results, unknowns=[], summary=Rationale("Complete grading")
    )
    assert result.ok is True


# =============================================================================
# Tests: Scoped Validation (reviewed_files filter)
# =============================================================================


@pytest_asyncio.fixture
async def grader_submit_server_file1_only(test_db, test_snapshot_with_tps, critique_with_3_issues):
    """Create GraderSubmitServer with only file1.py in scope (1 expected occurrence)."""
    # Only file1.py reviewed = only tp-001/occ-001 is catchable
    return _make_grader_submit_server(test_snapshot_with_tps, critique_with_3_issues, reviewed_files={Path("file1.py")})


async def test_submit_scoped_validation_accepts_only_catchable(grader_submit_server_file1_only):
    """With scoped validation, only catchable occurrences must be graded."""
    server, context = grader_submit_server_file1_only

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
    result = await server.submit_result_tool.fn(
        occurrence_results=occurrence_results, unknowns=unknowns, summary=Rationale("Scoped grading (file1.py only)")
    )
    assert result.ok is True


async def test_submit_scoped_validation_refuses_out_of_scope(grader_submit_server_file1_only):
    """With scoped validation, cannot grade occurrences not in scope."""
    server, context = grader_submit_server_file1_only

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
        await server.submit_result_tool.fn(
            occurrence_results=occurrence_results, unknowns=unknowns, summary=Rationale("Invalid submission")
        )

    error_message = str(exc_info.value)
    assert "Unexpected TP occurrence(s) not in scope" in error_message
    assert "tp-002/occ-002-a" in error_message


# =============================================================================
# Tests: Input Critique Validation (existing validation)
# =============================================================================


async def test_submit_refuses_unaccounted_input_issue(grader_submit_server_all_files):
    """Every critique issue must be matched to TPs or marked as unknown."""
    server, context = grader_submit_server_all_files

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
        await server.submit_result_tool.fn(
            occurrence_results=occurrence_results,
            unknowns=unknowns,
            summary=Rationale("Incomplete accounting of inputs"),
        )

    error_message = str(exc_info.value)
    assert "Input critique issues not accounted for" in error_message
    assert "input-003" in error_message


async def test_submit_refuses_invalid_unknown_id(grader_submit_server_all_files):
    """Unknown issue IDs must come from the input critique."""
    server, context = grader_submit_server_all_files

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
        await server.submit_result_tool.fn(
            occurrence_results=occurrence_results, unknowns=unknowns, summary=Rationale("Invalid unknown ID test")
        )

    error_message = str(exc_info.value)
    assert "Unknown issue IDs not from input critique" in error_message
    assert "invalid-999" in error_message
