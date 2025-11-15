"""Tests for CLI functionality."""

import os
from pathlib import Path

from click.testing import CliRunner
from difftree.__main__ import main
import pytest

from .conftest import create_file, git_add_commit


@pytest.fixture
def runner():
    """Create Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def git_repo_with_changes(temp_git_repo: Path, run_git) -> Path:
    create_file(temp_git_repo, "src/main.py", "line1\n")
    create_file(temp_git_repo, "src/utils.py", "line1\n")
    git_add_commit(run_git)

    create_file(temp_git_repo, "src/main.py", "line1\nline2\nline3\n")
    create_file(temp_git_repo, "README.md", "# Project\n")

    return temp_git_repo


def test_cli_default_columns(runner, git_repo_with_changes):
    """Test CLI with default columns (all enabled)."""
    result = runner.invoke(main, [], obj={}, catch_exceptions=False, env={"PWD": str(git_repo_with_changes)})

    # Should succeed (exit code 0)
    assert result.exit_code == 0
    # Should have some output (tree structure)
    assert result.output.strip() != ""


def test_cli_columns_flag_all(runner, git_repo_with_changes):
    """Test --columns flag with all columns."""
    result = runner.invoke(main, ["--columns", "tree,counts,bars,percentages"], obj={}, catch_exceptions=False)

    assert result.exit_code == 0
    # Should show content
    assert result.output.strip() != ""


def test_cli_columns_flag_minimal(runner, git_repo_with_changes):
    """Test --columns flag with only tree column."""
    result = runner.invoke(main, ["--columns", "tree"], obj={}, catch_exceptions=False)

    assert result.exit_code == 0
    # Should show tree structure
    assert result.output.strip() != ""


def test_cli_columns_flag_custom_order(runner, git_repo_with_changes):
    """Test --columns flag with custom column ordering."""
    result = runner.invoke(
        main,
        ["--columns", "tree,bars,counts"],  # Different order
        obj={},
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_cli_columns_flag_invalid_column(runner, git_repo_with_changes):
    """Test --columns flag with invalid column name."""
    result = runner.invoke(main, ["--columns", "tree,invalid,counts"], obj={}, catch_exceptions=False)

    # Should fail with Click parameter error (exit code 2)
    assert result.exit_code == 2
    assert "Unknown column" in result.output
    assert "invalid" in result.output.lower()


def test_cli_columns_flag_case_insensitive(runner, git_repo_with_changes):
    """Test --columns flag is case-insensitive."""
    result = runner.invoke(
        main,
        ["--columns", "TREE,CoUnTs,BaRs"],  # Mixed case
        obj={},
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_cli_columns_flag_with_spaces(runner, git_repo_with_changes):
    """Test --columns flag handles spaces correctly."""
    result = runner.invoke(
        main,
        ["--columns", "tree, counts, bars"],  # Spaces after commas
        obj={},
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_cli_sort_alpha(runner, git_repo_with_changes):
    """Test --sort alpha option."""
    result = runner.invoke(main, ["--sort", "alpha"], obj={}, catch_exceptions=False)

    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_cli_sort_size(runner, git_repo_with_changes):
    """Test --sort size option (default)."""
    result = runner.invoke(main, ["--sort", "size"], obj={}, catch_exceptions=False)

    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_cli_max_depth(runner, git_repo_with_changes):
    """Test --max-depth option."""
    result = runner.invoke(main, ["--max-depth", "1"], obj={}, catch_exceptions=False)

    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_cli_bar_width(runner, git_repo_with_changes):
    """Test --bar-width option."""
    result = runner.invoke(main, ["--bar-width", "30"], obj={}, catch_exceptions=False)

    assert result.exit_code == 0
    assert result.output.strip() != ""


def test_cli_no_changes(runner, temp_git_repo, run_git, monkeypatch):
    create_file(temp_git_repo, "file.py", "line1\n")
    git_add_commit(run_git)

    monkeypatch.chdir(temp_git_repo)
    result = runner.invoke(main, [])

    assert result.exit_code == 0
    assert "No changes" in result.output


def test_cli_combined_options(runner, git_repo_with_changes):
    """Test CLI with multiple options combined."""
    result = runner.invoke(
        main,
        ["--columns", "tree,counts,bars", "--sort", "alpha", "--bar-width", "15", "--max-depth", "2"],
        obj={},
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.output.strip() != ""


# CLI Integration Tests


def test_cli_integration_basic(runner, temp_git_repo, run_git, monkeypatch):
    create_file(temp_git_repo, "file.py", "line1\n")
    git_add_commit(run_git)
    create_file(temp_git_repo, "file.py", "line1\nline2\n")

    monkeypatch.chdir(temp_git_repo)
    result = runner.invoke(main, [])

    assert result.exit_code == 0
    assert "file.py" in result.output
    assert "+1" in result.output


def test_cli_integration_with_args(runner, temp_git_repo, run_git, monkeypatch):
    create_file(temp_git_repo, "file.py", "v1\n")
    git_add_commit(run_git)
    create_file(temp_git_repo, "file.py", "v2\n")
    git_add_commit(run_git)

    monkeypatch.chdir(temp_git_repo)
    result = runner.invoke(main, ["HEAD~1", "HEAD"])

    assert result.exit_code == 0
    assert "file.py" in result.output
    assert "+1" in result.output
    assert "-1" in result.output


def test_cli_integration_invalid_column(runner, temp_git_repo, run_git, monkeypatch):
    create_file(temp_git_repo, "file.py", "line1\n")
    git_add_commit(run_git)
    create_file(temp_git_repo, "file.py", "line1\nline2\n")

    monkeypatch.chdir(temp_git_repo)
    result = runner.invoke(main, ["--columns", "tree,invalid"])

    assert result.exit_code == 2
    assert "Unknown column" in result.output
    assert "invalid" in result.output
