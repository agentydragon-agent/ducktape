"""Tests for the definition_stats_whole_repo example module.

Tests functions for whole-repo mode definition statistics (uses SECURITY DEFINER function).
Consolidated from: test_query_train_vs_valid_performance_whole_repo.
"""

from adgn.props.agent_defs.prompt_optimizer.examples.definition_stats_whole_repo import show_train_vs_valid


def test_show_train_vs_valid_with_data(
    test_train_example_with_runs, test_valid_example_with_runs, capsys
):
    """Test that show_train_vs_valid produces combined train/valid output in whole-repo mode."""

    show_train_vs_valid()

    captured = capsys.readouterr()
    output = captured.out

    assert "Train vs Validation Performance (whole-repo mode" in output

    lines = output.strip().split("\n")

    assert any("train" in line.lower() for line in lines), "Expected 'train' split in output"
    assert any("valid" in line.lower() for line in lines), "Expected 'valid' split in output"
    assert any("UCB" in line or "ucb" in line.lower() for line in lines), "Expected UCB column in output"
    assert any("LCB" in line or "lcb" in line.lower() for line in lines), "Expected LCB column in output"


def test_show_train_vs_valid_empty(test_db, capsys):
    """Test that show_train_vs_valid handles empty database gracefully in whole-repo mode."""
    show_train_vs_valid()

    captured = capsys.readouterr()
    output = captured.out

    assert "Train vs Validation Performance (whole-repo mode" in output
