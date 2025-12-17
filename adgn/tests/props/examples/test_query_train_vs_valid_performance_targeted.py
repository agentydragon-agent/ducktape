"""Tests for the query_train_vs_valid_performance_targeted example script."""

import pytest


def test_query_train_vs_valid_performance_targeted_with_data(
    test_train_example_with_runs, test_valid_example_with_runs, mock_agent_setup, capsys
):
    """Test that query_train_vs_valid_performance_targeted produces combined train/valid output.

    Uses test fixture runs for both train and valid splits.
    """
    from adgn.props.examples.query_train_vs_valid_performance_targeted import main  # noqa: PLC0415

    # Fixtures already created the examples and runs we need
    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Train vs Validation Performance (targeted mode" in output

    lines = output.strip().split("\n")

    # Verify both splits appear in output
    assert any("train" in line.lower() for line in lines), "Expected 'train' split in output"
    assert any("valid" in line.lower() for line in lines), "Expected 'valid' split in output"

    # Verify UCB and LCB columns appear in header or data
    # (They should be in the table header or column names)
    assert any("UCB" in line or "ucb" in line.lower() for line in lines), "Expected UCB column in output"
    assert any("LCB" in line or "lcb" in line.lower() for line in lines), "Expected LCB column in output"


def test_query_train_vs_valid_performance_targeted_empty(test_db, mock_agent_setup, capsys):
    """Test that query_train_vs_valid_performance_targeted handles empty database gracefully."""
    from adgn.props.examples.query_train_vs_valid_performance_targeted import main  # noqa: PLC0415

    main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header even with no data
    assert "Train vs Validation Performance (targeted mode" in output
