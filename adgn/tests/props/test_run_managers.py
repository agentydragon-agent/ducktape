"""Test run managers (path computation, persistence, factory methods)."""

from datetime import datetime
import json
from pathlib import Path

from hamcrest import assert_that, equal_to, instance_of
import pytest

from adgn.props.critic import CriticErrorPayload, CriticSubmitPayload
from adgn.props.grader import GradeSubmitInput
from adgn.props.run_managers import CriticRun, FullSplitEvalRun, GraderRun
from adgn.props.run_models import (
    CriticFailure,
    CriticInput,
    CriticSuccess,
    FullSplitEvalInput,
    GraderInput,
    GraderOutput,
    SpecimenScope,
)
from adgn.props.runs_context import RunsContext
from adgn.props.splits import Split


class TestCriticRunPathComputation:
    """Tests for CriticRun path computation (never parse paths)."""

    def test_path_format_specimen_scope(self, tmp_path: Path):
        """CriticRun should compute path: runs/{split}/critic/{scope_id}/{timestamp}/"""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4")
        run = CriticRun(critic_input, ctx=RunsContext(tmp_path))

        timestamp = datetime(2025, 1, 27, 15, 30, 45)
        path = run._build_run_path(timestamp)

        expected = tmp_path / "train" / "critic" / "specimen:ducktape" / "2025-11-26-00" / "20250127T153045"
        assert_that(path, equal_to(expected))

    def test_run_type_identifier(self, tmp_path: Path):
        """CriticRun.run_type should be 'critic'."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4")
        run = CriticRun(critic_input, ctx=RunsContext(tmp_path))

        assert_that(run.run_type, equal_to("critic"))


class TestGraderRunPathComputation:
    """Tests for GraderRun path computation."""

    def test_path_format_specimen_scope(self, tmp_path: Path):
        """GraderRun should compute path: runs/{split}/grader/{scope_id}/{timestamp}/"""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-21-repo")
        critic_output = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grader_input = GraderInput(scope=scope, critic_result=critic_output, model="claude-sonnet-4")
        run = GraderRun(grader_input, ctx=RunsContext(tmp_path))

        timestamp = datetime(2025, 1, 27, 15, 31, 45)
        path = run._build_run_path(timestamp)

        expected = tmp_path / "valid" / "grader" / "specimen:ducktape" / "2025-11-21-repo" / "20250127T153145"
        assert_that(path, equal_to(expected))

    def test_run_type_identifier(self, tmp_path: Path):
        """GraderRun.run_type should be 'grader'."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_output = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grader_input = GraderInput(scope=scope, critic_result=critic_output, model="claude-sonnet-4")
        run = GraderRun(grader_input, ctx=RunsContext(tmp_path))

        assert_that(run.run_type, equal_to("grader"))


class TestFullSplitEvalRunPathComputation:
    """Tests for FullSplitEvalRun path computation."""

    def test_path_format_split_scope(self, tmp_path: Path):
        """FullSplitEvalRun should compute path: runs/evals/full-split:{split}/{timestamp}/"""
        eval_input = FullSplitEvalInput(
            split=Split.VALID, critic_model="claude-sonnet-4", grader_model="claude-sonnet-4"
        )
        run = FullSplitEvalRun(eval_input, ctx=RunsContext(tmp_path))

        timestamp = datetime(2025, 1, 27, 16, 0, 0)
        path = run._build_run_path(timestamp)

        expected = tmp_path / "evals" / "full-split:valid" / "20250127T160000"
        assert_that(path, equal_to(expected))

    def test_run_type_identifier(self, tmp_path: Path):
        """FullSplitEvalRun.run_type should be 'full-split-eval'."""
        eval_input = FullSplitEvalInput(
            split=Split.TRAIN, critic_model="claude-sonnet-4", grader_model="claude-sonnet-4"
        )
        run = FullSplitEvalRun(eval_input, ctx=RunsContext(tmp_path))

        assert_that(run.run_type, equal_to("full-split-eval"))


class TestRunPersistence:
    """Tests for input/output persistence to disk."""

    def test_critic_run_save_input(self, tmp_path: Path):
        """CriticRun should persist input to input.json."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4", prompt_hash="abc123")
        run = CriticRun(critic_input, ctx=RunsContext(tmp_path))

        input_path = run.save_input()

        assert_that(input_path.exists())
        loaded = json.loads(input_path.read_text())
        assert_that(loaded["model"], equal_to("claude-sonnet-4"))
        assert_that(loaded["prompt_hash"], equal_to("abc123"))
        assert_that(loaded["scope"]["tag"], equal_to("specimen"))

    def test_critic_run_save_output_success(self, tmp_path: Path):
        """CriticRun should persist successful output to output.json."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4")
        run = CriticRun(critic_input, ctx=RunsContext(tmp_path))

        run.save_input()  # Ensure run_dir is created
        output = CriticSuccess(result=CriticSubmitPayload(issues=[]), timestamp=datetime(2025, 1, 27, 15, 30))
        output_path = run.save_output(output)

        assert_that(output_path.exists())
        loaded = json.loads(output_path.read_text())
        assert_that(loaded["tag"], equal_to("success"))
        assert_that(loaded["result"]["issues"], equal_to([]))

    def test_critic_run_save_output_failure(self, tmp_path: Path):
        """CriticRun should persist failure output to output.json."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4")
        run = CriticRun(critic_input, ctx=RunsContext(tmp_path))

        run.save_input()
        output = CriticFailure(
            error=CriticErrorPayload(message="Failed to analyze"), timestamp=datetime(2025, 1, 27, 15, 30)
        )
        output_path = run.save_output(output)

        assert_that(output_path.exists())
        loaded = json.loads(output_path.read_text())
        assert_that(loaded["tag"], equal_to("failure"))
        assert_that(loaded["error"]["message"], equal_to("Failed to analyze"))

    def test_grader_run_save_output(self, tmp_path: Path):
        """GraderRun should persist output with full GradeSubmitInput."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_output = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grader_input = GraderInput(scope=scope, critic_result=critic_output, model="claude-sonnet-4")
        run = GraderRun(grader_input, ctx=RunsContext(tmp_path))

        run.save_input()
        grade = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": {},
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 0.0, "fp": 0.0, "unlabeled": 1.0},
                "recall": 0.0,
                "summary": "Test summary for grader persistence",
            }
        )
        output = GraderOutput(grade=grade, timestamp=datetime(2025, 1, 27, 15, 30))
        output_path = run.save_output(output)

        assert_that(output_path.exists())
        loaded = json.loads(output_path.read_text())
        assert_that(loaded["grade"]["recall"], equal_to(0.0))
        assert_that(loaded["grade"]["summary"], equal_to("Test summary for grader persistence"))


class TestRunLoading:
    """Tests for loading runs from disk (factory methods)."""

    def test_load_critic_input(self, tmp_path: Path):
        """CriticRun.load_input() should restore CriticInput from disk."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4", prompt_hash="xyz789")
        ctx = RunsContext(tmp_path)
        run = CriticRun(critic_input, ctx=ctx)
        run.save_input()

        run_dir = run.run_dir
        assert run_dir is not None
        loaded = CriticRun.load_input(run_dir, CriticInput, ctx)

        assert_that(loaded, instance_of(CriticInput))
        assert_that(loaded.model, equal_to("claude-sonnet-4"))
        assert_that(loaded.prompt_hash, equal_to("xyz789"))
        assert_that(loaded.scope, instance_of(SpecimenScope))

    def test_load_critic_output_success(self, tmp_path: Path):
        """CriticRun.load_output() should restore CriticSuccess from disk."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4")
        ctx = RunsContext(tmp_path)
        run = CriticRun(critic_input, ctx=ctx)
        run.save_input()

        output = CriticSuccess(result=CriticSubmitPayload(issues=[]), timestamp=datetime(2025, 1, 27, 15, 30))
        run.save_output(output)

        run_dir = run.run_dir
        assert run_dir is not None
        loaded = CriticRun.load_output(run_dir, CriticSuccess, ctx)

        assert_that(loaded, instance_of(CriticSuccess))
        assert_that(loaded.tag, equal_to("success"))

    def test_load_critic_output_failure(self, tmp_path: Path):
        """CriticRun.load_output() should restore CriticFailure from disk."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4")
        ctx = RunsContext(tmp_path)
        run = CriticRun(critic_input, ctx=ctx)
        run.save_input()

        output = CriticFailure(error=CriticErrorPayload(message="Test error"), timestamp=datetime(2025, 1, 27, 15, 30))
        run.save_output(output)

        run_dir = run.run_dir
        assert run_dir is not None
        loaded = CriticRun.load_output(run_dir, CriticFailure, ctx)

        assert_that(loaded, instance_of(CriticFailure))
        assert_that(loaded.tag, equal_to("failure"))
        assert_that(loaded.error.message, equal_to("Test error"))

    def test_load_grader_output(self, tmp_path: Path):
        """GraderRun.load_output() should restore GraderOutput with full type safety."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_output = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grader_input = GraderInput(scope=scope, critic_result=critic_output, model="claude-sonnet-4")
        ctx = RunsContext(tmp_path)
        run = GraderRun(grader_input, ctx=ctx)
        run.save_input()

        grade = GradeSubmitInput.model_validate(
            {
                "canonical_tp_coverage": {
                    "issue-001": {"covered_by": {"input-001": 1.0}, "recall_credit": 1.0, "reasoning": "Fully covered"}
                },
                "canonical_fp_coverage": {},
                "novel_critique_issues": {},
                "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
                "recall": 1.0,
                "summary": "Perfect recall",
            }
        )
        output = GraderOutput(grade=grade, timestamp=datetime(2025, 1, 27, 15, 30))
        run.save_output(output)

        run_dir = run.run_dir
        assert run_dir is not None
        loaded = GraderRun.load_output(run_dir, GraderOutput, ctx)

        assert_that(loaded, instance_of(GraderOutput))
        assert_that(loaded.recall, equal_to(1.0))
        assert_that(loaded.grade.summary, equal_to("Perfect recall"))


class TestRunExecution:
    """Tests for run execution.

    Note: These tests require live LLM calls and are marked as such.
    The execute() methods are now implemented and wrap agent_runners.py functions.
    """

    @pytest.mark.asyncio
    @pytest.mark.live_llm
    async def test_critic_run_execute_requires_live_llm(self, tmp_path: Path):
        """CriticRun.execute() is now implemented but requires live LLM (skip in unit tests)."""
        # This test documents that execute() is implemented
        # Actual execution requires OpenAI client, prompts, etc.
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_input = CriticInput(scope=scope, model="claude-sonnet-4")
        _run = CriticRun(critic_input, ctx=RunsContext(tmp_path))

        # Execute requires runtime parameters (client, prompts)
        # This would work in integration tests with proper setup:
        # output = await _run.execute(client=client, system_prompt="...", user_prompt="...")
        pytest.skip("Requires live LLM for integration testing")

    @pytest.mark.asyncio
    @pytest.mark.live_llm
    async def test_grader_run_execute_requires_live_llm(self, tmp_path: Path):
        """GraderRun.execute() is now implemented but requires live LLM (skip in unit tests)."""
        scope = SpecimenScope(specimen_slug="ducktape/2025-11-26-00")
        critic_output = CriticSuccess(result=CriticSubmitPayload(issues=[]))
        grader_input = GraderInput(scope=scope, critic_result=critic_output, model="claude-sonnet-4")
        _run = GraderRun(grader_input, ctx=RunsContext(tmp_path))

        # Execute requires runtime parameters (client, scope_text)
        # This would work in integration tests with proper setup:
        # output = await _run.execute(client=client, scope_text="Specimen: ...")
        pytest.skip("Requires live LLM for integration testing")

    @pytest.mark.asyncio
    async def test_full_split_eval_run_execute_not_implemented(self, tmp_path: Path):
        """FullSplitEvalRun.execute() is still a stub (orchestration not yet implemented)."""
        eval_input = FullSplitEvalInput(
            split=Split.TRAIN, critic_model="claude-sonnet-4", grader_model="claude-sonnet-4"
        )
        run = FullSplitEvalRun(eval_input, ctx=RunsContext(tmp_path))

        with pytest.raises(NotImplementedError, match=r"FullSplitEvalRun\.execute"):
            await run.execute()
