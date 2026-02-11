"""Test critic and grader models (scope types, input/output models, discriminated unions).

Tests for models defined in critic.py and grader.py.
"""

from pathlib import Path
from uuid import uuid4

from hamcrest import assert_that, equal_to
import pytest

from adgn.props.critic.models import ALL_FILES_WITH_ISSUES, CriticInput, CriticSubmitPayload, CriticSuccess
from adgn.props.grader.models import GraderInput, GraderOutput, GradeSubmitInput
from adgn.props.ids import SnapshotSlug


@pytest.fixture
def mock_snapshot_slug() -> SnapshotSlug:
    """Shared test snapshot slug."""
    return SnapshotSlug("ducktape/2025-11-26-00")


class TestCriticModels:
    """Tests for critic input/output models."""

    def test_critic_input_valid(self, mock_snapshot_slug: SnapshotSlug, mock_prompt_sha256: str):
        """CriticInput should accept valid snapshot_slug, files, and prompt hash."""
        critic_input = CriticInput(
            snapshot_slug=mock_snapshot_slug, files={Path("src/main.py")}, prompt_sha256=mock_prompt_sha256
        )

        assert_that(critic_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(critic_input.files, equal_to({Path("src/main.py")}))
        assert_that(critic_input.prompt_sha256, equal_to(mock_prompt_sha256))

    def test_critic_input_with_sentinel(self, mock_snapshot_slug: SnapshotSlug, mock_prompt_sha256: str):
        """CriticInput should accept ALL_FILES_WITH_ISSUES sentinel."""
        critic_input = CriticInput(
            snapshot_slug=mock_snapshot_slug, files=ALL_FILES_WITH_ISSUES, prompt_sha256=mock_prompt_sha256
        )

        assert_that(critic_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(critic_input.files, equal_to(ALL_FILES_WITH_ISSUES))

    def test_critic_success_variant(self):
        """CriticSuccess should wrap successful critique result."""
        result = CriticSubmitPayload(issues=[], notes_md="All good")
        success = CriticSuccess(result=result)

        assert_that(success.tag, equal_to("success"))
        assert_that(success.result, equal_to(result))
        assert_that(isinstance(success, CriticSuccess))


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
                "canonical_tp_coverage": {
                    "issue-001": {"covered_by": {"input-001": 1.0}, "recall_credit": 1.0, "rationale": "Fully covered"},
                    "issue-002": {"covered_by": {}, "recall_credit": 0.0, "rationale": "Not covered"},
                },
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
                "recall": 0.5,
                "summary": "Test summary",
                "per_file_recall": {},
                "per_file_ratios": {},
            }
        )

        output = GraderOutput(grade=grade)

        assert_that(output.recall, equal_to(0.5))
        assert_that(output.coverage_recall, equal_to(0.5))  # (1.0 + 0.0) / 2

    def test_grader_output_coverage_recall_none_when_no_tps(self):
        """GraderOutput.coverage_recall should be None when no canonical TPs."""
        grade = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": {},
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 0.0, "fp": 0.0, "unlabeled": 1.0},
                "recall": 0.0,
                "summary": "No canonicals",
                "per_file_recall": {},
                "per_file_ratios": {},
            }
        )

        output = GraderOutput(grade=grade)
        assert_that(output.coverage_recall, equal_to(None))


class TestFullSplitEvalModels:
    """Tests for orchestrated eval input/output models."""
