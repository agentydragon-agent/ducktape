"""Tests for the query_valid_examples example script."""

from adgn.props.db import get_session
from adgn.props.db.models import Snapshot


def test_query_valid_examples_with_synced_data(synced_test_fixtures, mock_agent_setup, capsys):
    """Test that query_valid_examples produces reasonable output with valid snapshots."""
    from adgn.props.examples.query_valid_examples import main  # noqa: PLC0415

    # Verify we have valid snapshots
    with get_session() as session:
        valid_snapshots = session.query(Snapshot).filter(Snapshot.split == "valid").all()

        # Remember first snapshot for verification
        expected_snapshot = valid_snapshots[0].slug
        total_valid_count = len(valid_snapshots)

    main()

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Validation snapshots" in output
    assert f"{total_valid_count} total" in output or f"({total_valid_count} total)" in output

    # Verify specific snapshot appears
    assert expected_snapshot in output, f"Expected snapshot slug '{expected_snapshot}' in output"


def test_query_valid_examples_empty_database(test_db, mock_agent_setup, capsys):
    """Test that query_valid_examples handles empty database gracefully."""
    from adgn.props.examples.query_valid_examples import main  # noqa: PLC0415

    main()

    captured = capsys.readouterr()
    output = captured.out

    # Should show header with 0 snapshots
    assert "Validation snapshots" in output
    assert "0 total" in output or "(0 total)" in output
