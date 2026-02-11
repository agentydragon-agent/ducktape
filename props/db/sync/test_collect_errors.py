"""Tests for error collection in sync operations."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import pytest_bazel
import yaml
from pydantic import ValidationError

from props.core.ids import SnapshotSlug
from props.db.sync.yaml_loader import SyncValidationError, load_yaml_issues


@pytest.fixture
def snapshot_dir(tmp_path: Path) -> Path:
    """Create a snapshot directory with a mix of valid and invalid YAML issue files."""
    repo_dir = tmp_path / "test-repo" / "2026-01-01-00"
    issues_dir = repo_dir / "issues"
    issues_dir.mkdir(parents=True)

    # Valid issue file
    (issues_dir / "valid-issue.yaml").write_text(
        dedent("""\
        rationale: |
          This is a valid test issue with enough characters to pass validation.
        should_flag: true
        occurrences:
          - occurrence_id: occ-0
            files:
              src/foo.py:
                - [1, 10]
    """)
    )

    # Invalid: missing required fields
    (issues_dir / "bad-missing-fields.yaml").write_text(
        dedent("""\
        rationale: "short"
    """)
    )

    # Invalid: bad YAML syntax
    (issues_dir / "bad-syntax.yaml").write_text(
        dedent("""\
        rationale: |
          Some text
        should_flag: [invalid
    """)
    )

    return repo_dir


def test_collect_errors_false_raises_on_first_error(snapshot_dir: Path) -> None:
    """Default behavior: fail on first invalid file."""
    slug = SnapshotSlug("test-repo/2026-01-01-00")
    specimens_dir = snapshot_dir.parent.parent

    with pytest.raises((yaml.YAMLError, ValidationError)):
        load_yaml_issues(slug, specimens_dir, collect_errors=False)


def test_collect_errors_true_collects_all_errors(snapshot_dir: Path) -> None:
    """With collect_errors=True, all files are attempted and all errors reported."""
    slug = SnapshotSlug("test-repo/2026-01-01-00")
    specimens_dir = snapshot_dir.parent.parent

    with pytest.raises(SyncValidationError) as exc_info:
        load_yaml_issues(slug, specimens_dir, collect_errors=True)

    # Both bad files should be reported
    assert len(exc_info.value.errors) == 2
    error_text = str(exc_info.value)
    assert "bad-missing-fields.yaml" in error_text
    assert "bad-syntax.yaml" in error_text


def test_collect_errors_true_succeeds_when_all_valid(tmp_path: Path) -> None:
    """When all files are valid, collect_errors=True returns normally."""
    repo_dir = tmp_path / "good-repo" / "2026-01-01-00"
    issues_dir = repo_dir / "issues"
    issues_dir.mkdir(parents=True)

    (issues_dir / "valid.yaml").write_text(
        dedent("""\
        rationale: |
          A perfectly valid issue with sufficient rationale text for validation.
        should_flag: true
        occurrences:
          - occurrence_id: occ-0
            files:
              src/main.py:
                - [1, 5]
    """)
    )

    slug = SnapshotSlug("good-repo/2026-01-01-00")
    tps, fps = load_yaml_issues(slug, tmp_path, collect_errors=True)
    assert len(tps) == 1
    assert len(fps) == 0


if __name__ == "__main__":
    pytest_bazel.main()
