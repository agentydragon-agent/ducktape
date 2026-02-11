from pathlib import Path

import pytest

from adgn.props.models.lint import (
    AnchorIncorrect,
    Correction,
    FalsePositive,
    IssueLintFindingRecord,
    LintSubmitPayload,
    OtherError,
    TruePositive,
)
from adgn.props.models.true_positive import LineRange


def test_validation_accepts_single_false_positive():
    payload = LintSubmitPayload(
        message_md="OK", suggested_rationale=None, findings=[IssueLintFindingRecord(finding=FalsePositive())]
    )
    assert isinstance(payload, LintSubmitPayload)


def test_validation_accepts_single_true_positive():
    payload = LintSubmitPayload(message_md="OK", findings=[IssueLintFindingRecord(finding=TruePositive())])
    assert isinstance(payload, LintSubmitPayload)


def test_validation_accepts_other_error_without_tp_fp():
    payload = LintSubmitPayload(
        message_md="OK", findings=[IssueLintFindingRecord(finding=OtherError(description="parser failed"))]
    )
    assert isinstance(payload, LintSubmitPayload)


def test_validation_rejects_both_tp_and_fp_without_other_error():
    with pytest.raises(
        ValueError,
        match=(
            r"Findings must have: \(a\) exactly one false positive or true positive finding, "
            r"or \(b\) at least 1 'other error' finding"
        ),
    ):
        LintSubmitPayload(
            message_md="Bad mix",
            findings=[IssueLintFindingRecord(finding=TruePositive()), IssueLintFindingRecord(finding=FalsePositive())],
        )


def test_validation_rejects_no_tp_fp_and_no_other_error():
    # Only an anchor correction present — should fail because neither TP/FP nor OTHER_ERROR is present
    with pytest.raises(
        ValueError,
        match=(
            r"Findings must have: \(a\) exactly one false positive or true positive finding, "
            r"or \(b\) at least 1 'other error' finding"
        ),
    ):
        LintSubmitPayload(
            message_md="Missing TP/FP and OTHER_ERROR",
            findings=[
                IssueLintFindingRecord(
                    finding=AnchorIncorrect(
                        correction=Correction(file=Path("wt/wt/cli.py"), range=LineRange(start_line=143, end_line=152))
                    )
                )
            ],
        )


def test_validation_allows_fp_with_additional_non_tp_fp_findings():
    # FP plus an anchor correction is allowed (exactly one FP, others are fine)
    payload = LintSubmitPayload(
        message_md="OK",
        findings=[
            IssueLintFindingRecord(finding=FalsePositive()),
            IssueLintFindingRecord(
                finding=AnchorIncorrect(
                    correction=Correction(file=Path("wt/wt/cli.py"), range=LineRange(start_line=143, end_line=152))
                )
            ),
        ],
    )
    assert isinstance(payload, LintSubmitPayload)


def test_validation_rejects_multiple_false_positives():
    with pytest.raises(
        ValueError,
        match=(
            r"Findings must have: \(a\) exactly one false positive or true positive finding, "
            r"or \(b\) at least 1 'other error' finding"
        ),
    ):
        LintSubmitPayload(
            message_md="too many FPs",
            findings=[IssueLintFindingRecord(finding=FalsePositive()), IssueLintFindingRecord(finding=FalsePositive())],
        )
