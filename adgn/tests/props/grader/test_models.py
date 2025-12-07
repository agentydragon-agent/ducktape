"""Test grader models (input/output models, discriminated unions).

Tests for models defined in grader/models.py.
"""

from uuid import uuid4

from hamcrest import assert_that, equal_to
import pytest

from adgn.props.grader.models import GraderInput, GraderOutput, GradeSubmitInput
from adgn.props.ids import SnapshotSlug


@pytest.fixture
def mock_snapshot_slug() -> SnapshotSlug:
    """Shared test snapshot slug."""
    return SnapshotSlug("ducktape/2025-11-26-00")


class TestGraderModels:
    """Tests for grader input/output models."""

    def test_grader_input_valid(self, mock_snapshot_slug: SnapshotSlug):
        """GraderInput should accept snapshot_slug and critique_id."""
        critique_id = uuid4()
        grader_input = GraderInput(snapshot_slug=mock_snapshot_slug, critique_id=critique_id)

        assert_that(grader_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(grader_input.critique_id, equal_to(critique_id))

    def test_grader_output_valid(self):
        """GraderOutput should wrap GradeSubmitInput with computed properties."""
        grade = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": [
                    {
                        "canonical_id": "issue-001",
                        "coverage": {
                            "covered_by": [{"input_id": "input-001", "credit": 1.0}],
                            "recall_credit": 1.0,
                            "rationale": "Fully covered",
                        },
                    },
                    {
                        "canonical_id": "issue-002",
                        "coverage": {"covered_by": [], "recall_credit": 0.0, "rationale": "Not covered"},
                    },
                ],
                "canonical_fp_coverage": [],
                "novel_critique_issues": [],
                "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
                "recall": 0.5,
                "summary": "Test summary",
            }
        )

        output = GraderOutput(grade=grade)

        assert_that(output.recall, equal_to(0.5))
        assert_that(output.coverage_recall, equal_to(0.5))  # (1.0 + 0.0) / 2

    def test_grader_output_coverage_recall_none_when_no_tps(self):
        """GraderOutput.coverage_recall should be None when no canonical TPs."""
        grade = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": [],
                "canonical_fp_coverage": [],
                "novel_critique_issues": [],
                "reported_issue_ratios": {"tp": 0.0, "fp": 0.0, "unlabeled": 1.0},
                "recall": 0.0,
                "summary": "No canonicals",
            }
        )

        output = GraderOutput(grade=grade)
        assert_that(output.coverage_recall, equal_to(None))
