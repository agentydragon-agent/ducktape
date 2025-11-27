"""Tests for agent_runners module."""

from __future__ import annotations

from pathlib import Path

from adgn.props.agent_runners import export_unknown_issues_yaml
from adgn.props.grader import CritiqueInputIssue, GradeSubmitInput, NovelIssueReasoning, ReportedIssueRatios
from adgn.props.ids import InputIssueID
from adgn.props.models.issue import LineRange, Occurrence


def test_export_unknown_issues_yaml_uses_input_id_directly(tmp_path: Path):
    """Verify export_unknown_issues_yaml uses InputIssueID directly (not .id attribute).

    Regression test for bug where code tried input_id.id when InputIssueID
    is already a plain string at runtime (NewType).
    """
    # Create a grade with one novel issue
    grade = GradeSubmitInput(
        canonical_tp_coverage={},
        canonical_fp_coverage={},
        novel_critique_issues={
            InputIssueID("novel-issue-abc"): NovelIssueReasoning(
                reasoning="This is a new issue not in the canonical set"
            )
        },
        reported_issue_ratios=ReportedIssueRatios(tp=0.0, fp=0.0, unlabeled=1.0),
        recall=0.0,
        summary="All issues are novel.",
    )

    # Create a critique with matching issue (files must be plain strings for YAML serialization)
    critique_issues = [
        CritiqueInputIssue(
            id=InputIssueID("novel-issue-abc"),
            rationale="Issue found in code",
            occurrences=[
                Occurrence(files={Path("foo.py"): [LineRange(start_line=10, end_line=20)]}, note="First occurrence"),
                Occurrence(files={Path("bar.py"): [LineRange(start_line=5, end_line=8)]}, note="Second occurrence"),
            ],
        )
    ]

    # Export should create YAML files without error
    output_dir = tmp_path / "unknowns"
    export_unknown_issues_yaml(grade, critique_issues, output_dir)

    # Verify files were created with correct names (using InputIssueID as filename prefix)
    expected_files = [output_dir / "novel-issue-abc__occ0.yaml", output_dir / "novel-issue-abc__occ1.yaml"]

    for expected_file in expected_files:
        assert expected_file.exists(), f"Expected file not created: {expected_file}"
        # Verify YAML is valid and non-empty
        content = expected_file.read_text()
        assert len(content) > 0
        assert "novel-issue-abc" in content
