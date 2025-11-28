"""Test run models (scope types, input/output models, discriminated unions)."""

from datetime import datetime
from pathlib import Path

from hamcrest import assert_that, equal_to, has_length, instance_of
from pydantic import ValidationError
import pytest

from adgn.props.critic import CriticErrorPayload, CriticSubmitPayload, ReportedIssue
from adgn.props.grader import GradeSubmitInput
from adgn.props.run_models import (
    CriticFailure,
    CriticInput,
    CriticSuccess,
    FileScope,
    FullSplitEvalInput,
    FullSplitEvalOutput,
    GraderInput,
    GraderOutput,
    SpecimenEvalResult,
    SpecimenScope,
)
from adgn.props.splits import Split


class TestSpecimenScope:
    """Tests for SpecimenScope type (specimen-based evaluation)."""

    def test_valid_specimen_scope(self):
        """SpecimenScope should accept valid specimen slugs."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        assert_that(scope.specimen_slug, equal_to("ducktape/2025-11-26-00"))
        assert_that(scope.tag, equal_to("specimen"))

    def test_split_computed_from_specimen(self):
        """SpecimenScope.split should be computed from specimen membership."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        assert_that(scope.split, equal_to(Split.TRAIN))

    def test_scope_id_format(self):
        """SpecimenScope.scope_id() should format as specimen:{slug}."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        assert_that(scope.scope_id(), equal_to("specimen:ducktape/2025-11-26-00"))

    def test_rejects_invalid_specimen_slug(self):
        """SpecimenScope should reject invalid specimen slugs (wrong pattern)."""
        with pytest.raises(ValidationError):
            SpecimenScope(specimen_slug="no-slash")  # Must have exactly one slash

        with pytest.raises(ValidationError):
            SpecimenScope(specimen_slug="too/many/slashes")  # Only one slash allowed

    def test_frozen_model(self):
        """SpecimenScope should be immutable."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        with pytest.raises(ValidationError):
            scope.specimen_slug = "other/slug"


class TestFileScope:
    """Tests for FileScope type (file-based evaluation)."""

    def test_valid_file_scope(self):
        """FileScope should accept valid file paths."""

        scope = FileScope(path=Path("/tmp/my_module.py"))
        assert_that(scope.path, equal_to(Path("/tmp/my_module.py")))
        assert_that(scope.tag, equal_to("file"))

    def test_split_defaults_to_train(self):
        """FileScope.split should default to TRAIN."""

        scope = FileScope(path=Path("/tmp/test.py"))
        assert_that(scope.split, equal_to(Split.TRAIN))

    def test_scope_id_format(self):
        """FileScope.scope_id() should format as file:{stem}."""

        scope = FileScope(path=Path("/tmp/my_module.py"))
        assert_that(scope.scope_id(), equal_to("file:my_module"))

    def test_frozen_model(self):
        """FileScope should be immutable."""

        scope = FileScope(path=Path("/tmp/test.py"))
        with pytest.raises(ValidationError):
            scope.path = Path("/other/path.py")


class TestCriticModels:
    """Tests for critic input/output models."""

    def test_critic_input_valid(self):
        """CriticInput should accept valid scope and metadata."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4", prompt_hash="abc123", notes="Test run")

        assert_that(critic_input.scope, equal_to(scope))
        assert_that(critic_input.model, equal_to("claude-sonnet-4"))
        assert_that(critic_input.prompt_hash, equal_to("abc123"))
        assert_that(critic_input.notes, equal_to("Test run"))

    def test_critic_success_variant(self):
        """CriticSuccess should wrap successful critique result."""
        result = CriticSubmitPayload(issues=[], notes_md="All good")
        success = CriticSuccess(result=result, timestamp=datetime(2025, 1, 27, 15, 30))

        assert_that(success.tag, equal_to("success"))
        assert_that(success.result, equal_to(result))
        assert_that(isinstance(success, CriticSuccess))

    def test_critic_failure_variant(self):
        """CriticFailure should wrap error result."""
        error = CriticErrorPayload(message="Failed to analyze")
        failure = CriticFailure(error=error, timestamp=datetime(2025, 1, 27, 15, 30))

        assert_that(failure.tag, equal_to("failure"))
        assert_that(failure.error, equal_to(error))
        assert_that(isinstance(failure, CriticFailure))

    def test_critic_output_discriminated_union(self):
        """CriticOutput should be a discriminated union of success/failure."""
        # Success case
        result = CriticSubmitPayload(issues=[], notes_md="Done")
        success = CriticSuccess(result=result)
        assert_that(isinstance(success, CriticSuccess))

        # Failure case
        error = CriticErrorPayload(message="Error")
        failure = CriticFailure(error=error)
        assert_that(isinstance(failure, CriticFailure))

    def test_critic_output_serialization_round_trip(self):
        """CriticSuccess/CriticFailure should serialize and deserialize correctly."""
        # Success
        result = CriticSubmitPayload(issues=[ReportedIssue(id="test-issue", rationale="Test rationale")])
        success = CriticSuccess(result=result, timestamp=datetime(2025, 1, 27, 15, 30))
        dumped = success.model_dump(mode="json")
        restored = CriticSuccess.model_validate(dumped)
        assert_that(restored.tag, equal_to("success"))
        assert_that(restored.result.issues, has_length(1))

        # Failure
        error = CriticErrorPayload(message="Test error")
        failure = CriticFailure(error=error, timestamp=datetime(2025, 1, 27, 15, 30))
        dumped_failure = failure.model_dump(mode="json")
        restored_failure = CriticFailure.model_validate(dumped_failure)
        assert_that(restored_failure.tag, equal_to("failure"))
        assert_that(restored_failure.error.message, equal_to("Test error"))


class TestGraderModels:
    """Tests for grader input/output models."""

    def test_grader_input_valid(self):
        """GraderInput should accept valid scope, critic result, and metadata."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_result = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grader_input = GraderInput(
            scope=scope, critic_result=critic_result, model="claude-sonnet-4", critic_run_ref="/path/to/critic"
        )

        assert_that(grader_input.scope, equal_to(scope))
        assert_that(grader_input.critic_result, equal_to(critic_result))
        assert_that(grader_input.model, equal_to("claude-sonnet-4"))
        assert_that(grader_input.critic_run_ref, equal_to("/path/to/critic"))

    def test_grader_input_from_critic_output_factory(self):
        """GraderInput.from_critic_output() should construct GraderInput from CriticInput + CriticOutput."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4")
        critic_output = CriticSuccess(result=CriticSubmitPayload(issues=[]))

        grader_input = GraderInput.from_critic_output(
            critic_input, critic_output, model="claude-sonnet-4", critic_run_ref="/runs/critic/123"
        )

        assert_that(grader_input.scope, equal_to(scope))
        assert_that(grader_input.critic_result, equal_to(critic_output))
        assert_that(grader_input.model, equal_to("claude-sonnet-4"))
        assert_that(grader_input.critic_run_ref, equal_to("/runs/critic/123"))

    def test_grader_output_valid(self):
        """GraderOutput should wrap GradeSubmitInput with computed properties."""
        grade = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": {
                    "issue-001": {"covered_by": {"input-001": 1.0}, "recall_credit": 1.0, "reasoning": "Fully covered"},
                    "issue-002": {"covered_by": {}, "recall_credit": 0.0, "reasoning": "Not covered"},
                },
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
                "recall": 0.5,
                "summary": "Test summary",
            }
        )

        output = GraderOutput(grade=grade, timestamp=datetime(2025, 1, 27, 15, 30))

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
            }
        )

        output = GraderOutput(grade=grade)
        assert_that(output.coverage_recall, equal_to(None))


class TestFullSplitEvalModels:
    """Tests for orchestrated eval input/output models."""

    def test_full_split_eval_input_valid(self):
        """FullSplitEvalInput should accept valid split and model config."""
        eval_input = FullSplitEvalInput(
            split=Split.TRAIN,
            critic_model="claude-sonnet-4",
            grader_model="claude-sonnet-4",
            critic_prompt_hash="abc123",
            notes="Test eval",
        )

        assert_that(eval_input.split, equal_to(Split.TRAIN))
        assert_that(eval_input.critic_model, equal_to("claude-sonnet-4"))
        assert_that(eval_input.grader_model, equal_to("claude-sonnet-4"))
        assert_that(eval_input.critic_prompt_hash, equal_to("abc123"))

    def test_specimen_eval_result_construction(self):
        """SpecimenEvalResult should wrap specimen slug + outputs."""
        critic_output = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grade = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": {},
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 0.0, "fp": 0.0, "unlabeled": 1.0},
                "recall": 0.0,
                "summary": "Test summary for specimen eval",
            }
        )
        grader_output = GraderOutput(grade=grade)

        result = SpecimenEvalResult(
            specimen_slug="ducktape/2025-11-26-00", critic_output=critic_output, grader_output=grader_output
        )

        assert_that(result.specimen_slug, equal_to("ducktape/2025-11-26-00"))
        assert_that(result.critic_output, instance_of(CriticSuccess))
        assert_that(result.grader_output, equal_to(grader_output))

    def test_full_split_eval_output_aggregated_metrics(self):
        """FullSplitEvalOutput should compute aggregated metrics."""
        # Create two specimen results
        critic_success1 = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grade1 = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": {},
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 0.0, "fp": 0.0, "unlabeled": 1.0},
                "recall": 0.8,
                "summary": "Specimen 1",
            }
        )
        grader1 = GraderOutput(grade=grade1)
        result1 = SpecimenEvalResult(
            specimen_slug="ducktape/2025-11-26-00", critic_output=critic_success1, grader_output=grader1
        )

        critic_failure = CriticFailure(error=CriticErrorPayload(message="Failed"))
        result2 = SpecimenEvalResult(
            specimen_slug="ducktape/2025-11-20-00", critic_output=critic_failure, grader_output=None
        )

        critic_success2 = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grade2 = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": {},
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 0.0, "fp": 0.0, "unlabeled": 1.0},
                "recall": 0.6,
                "summary": "Specimen 3",
            }
        )
        grader2 = GraderOutput(grade=grade2)
        result3 = SpecimenEvalResult(
            specimen_slug="crush/2025-08-30-internal_db", critic_output=critic_success2, grader_output=grader2
        )

        output = FullSplitEvalOutput(split=Split.TRAIN, specimen_results=[result1, result2, result3])

        assert_that(output.total_specimens, equal_to(3))
        assert_that(output.successful_critiques, equal_to(2))
        assert_that(output.failed_critiques, equal_to(1))
        assert_that(output.avg_recall, equal_to(0.7))  # (0.8 + 0.6) / 2

    def test_full_split_eval_output_avg_recall_none_when_no_grades(self):
        """FullSplitEvalOutput.avg_recall should be None when no successful grades."""
        critic_failure = CriticFailure(error=CriticErrorPayload(message="Failed"))
        result = SpecimenEvalResult(
            specimen_slug="ducktape/2025-11-26-00", critic_output=critic_failure, grader_output=None
        )

        output = FullSplitEvalOutput(split=Split.TRAIN, specimen_results=[result])

        assert_that(output.avg_recall, equal_to(None))
