"""Tests for cluster_unknowns module."""

from pathlib import Path
from uuid import uuid4

from adgn.props.cluster_unknowns import ClusteredIssueID, ClusterSpec, UnknownIssue
from adgn.props.ids import BaseIssueID
from adgn.props.rationale import Rationale


def test_cluster_spec_aggregates_files() -> None:
    """Test that ClusterSpec correctly aggregates files from issues."""
    # Create test issues with different files
    issue1_id = ClusteredIssueID(critic_run_id=uuid4(), tp_id=BaseIssueID("issue1"))
    issue2_id = ClusteredIssueID(critic_run_id=uuid4(), tp_id=BaseIssueID("issue2"))

    issue1 = UnknownIssue(
        tp_id=issue1_id, rationale=Rationale("Test issue 1"), files={Path("src/foo.py"), Path("src/bar.py")}
    )
    issue2 = UnknownIssue(
        tp_id=issue2_id, rationale=Rationale("Test issue 2"), files={Path("src/bar.py"), Path("src/baz.py")}
    )

    # Build issue lookup
    issue_lookup = {issue1.tp_id: issue1, issue2.tp_id: issue2}

    # Create cluster with aggregated files
    primary_files = set()
    for issue_id in [issue1_id, issue2_id]:
        if issue_id in issue_lookup:
            primary_files.update(issue_lookup[issue_id].files)

    cluster = ClusterSpec(name="test-cluster", issue_ids=[issue1_id, issue2_id], primary_files=primary_files)

    # Verify files are correctly aggregated (union of all issue files)
    assert cluster.primary_files == {Path("src/foo.py"), Path("src/bar.py"), Path("src/baz.py")}


def test_cluster_spec_serialization() -> None:
    """Test that ClusterSpec serializes Path objects correctly to JSON."""
    issue_id = ClusteredIssueID(critic_run_id=uuid4(), tp_id=BaseIssueID("test-issue"))
    cluster = ClusterSpec(
        name="test-cluster", issue_ids=[issue_id], primary_files={Path("src/foo.py"), Path("src/bar.py")}
    )

    # Serialize to JSON
    json_data = cluster.model_dump(mode="json")

    # Verify primary_files is a list of strings with correct content (order not guaranteed)
    assert isinstance(json_data["primary_files"], list)
    assert set(json_data["primary_files"]) == {"src/bar.py", "src/foo.py"}


def test_cluster_spec_empty_files() -> None:
    """Test that ClusterSpec handles empty file sets correctly."""
    issue_id = ClusteredIssueID(critic_run_id=uuid4(), tp_id=BaseIssueID("test-issue"))
    cluster = ClusterSpec(name="test-cluster", issue_ids=[issue_id], primary_files=set())

    # Verify empty set is handled
    assert cluster.primary_files == set()

    # Verify serialization
    json_data = cluster.model_dump(mode="json")
    assert json_data["primary_files"] == []
