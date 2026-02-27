"""Tests for approval_gate predicate system."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel

from approval_gate.predicates import Approved, Denied, NeedsHumanDecision, call_predicate, load_predicate


def test_load_predicate_none_returns_failsafe():
    fn = load_predicate(None)
    result = fn("any_tool", {})
    assert isinstance(result, NeedsHumanDecision)


def test_load_predicate_missing_file_returns_failsafe(tmp_path: Path):
    fn = load_predicate(tmp_path / "nonexistent.py")
    result = fn("any_tool", {})
    assert isinstance(result, NeedsHumanDecision)


def test_load_predicate_approved(tmp_path: Path):
    predicate_file = tmp_path / "predicate.py"
    predicate_file.write_text(
        "from approval_gate.predicates import Approved\ndef decide(tool_name, arguments): return Approved()\n"
    )
    fn = load_predicate(predicate_file)
    result = fn("exec", {"argv": ["echo", "hi"]})
    assert isinstance(result, Approved)


def test_load_predicate_denied(tmp_path: Path):
    predicate_file = tmp_path / "predicate.py"
    predicate_file.write_text(
        "from approval_gate.predicates import Denied\ndef decide(tool_name, arguments): return Denied(reason='no')\n"
    )
    fn = load_predicate(predicate_file)
    result = fn("exec", {})
    assert isinstance(result, Denied)
    assert result.reason == "no"


def test_load_predicate_conditional(tmp_path: Path):
    predicate_file = tmp_path / "predicate.py"
    predicate_file.write_text(
        "from approval_gate.predicates import Approved, NeedsHumanDecision\n"
        "def decide(tool_name, arguments):\n"
        "    if tool_name == 'safe': return Approved()\n"
        "    return NeedsHumanDecision()\n"
    )
    fn = load_predicate(predicate_file)
    assert isinstance(fn("safe", {}), Approved)
    assert isinstance(fn("dangerous", {}), NeedsHumanDecision)


def test_load_predicate_syntax_error_returns_failsafe(tmp_path: Path):
    predicate_file = tmp_path / "predicate.py"
    predicate_file.write_text("this is not valid python !!!")
    fn = load_predicate(predicate_file)
    # Should fall back to NeedsHumanDecision, not raise
    result = fn("any", {})
    assert isinstance(result, NeedsHumanDecision)


def test_call_predicate_catches_runtime_exception():
    def bad_predicate(tool_name: str, arguments: dict):
        raise RuntimeError("predicate crashed!")

    result = call_predicate(bad_predicate, "tool", {})
    assert isinstance(result, NeedsHumanDecision)


def test_call_predicate_passes_through_approved():
    def always_approve(tool_name: str, arguments: dict):
        return Approved()

    result = call_predicate(always_approve, "tool", {})
    assert isinstance(result, Approved)


def test_call_predicate_passes_through_denied():
    def always_deny(tool_name: str, arguments: dict):
        return Denied(reason="policy")

    result = call_predicate(always_deny, "tool", {})
    assert isinstance(result, Denied)
    assert result.reason == "policy"


if __name__ == "__main__":
    pytest_bazel.main()
