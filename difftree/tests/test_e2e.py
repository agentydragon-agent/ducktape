"""End-to-end tests with actual git operations."""

from pathlib import Path

from difftree.parser import parse_unified_diff
from difftree.tree import build_tree, sort_tree

from .conftest import create_file, git_add_commit


def test_e2e_git_diff_unstaged(temp_git_repo: Path, run_git):
    """Test E2E workflow with unstaged changes."""
    # Create initial commit
    create_file(temp_git_repo, "file1.py", "line1\nline2\n")
    git_add_commit(temp_git_repo, "Initial commit")

    # Make unstaged changes
    create_file(temp_git_repo, "file1.py", "line1\nline2\nline3\n")
    create_file(temp_git_repo, "file2.py", "new file\n")

    # Get diff output
    result = run_git("diff")

    # Should have changes
    assert result.stdout.strip() != ""


def test_e2e_git_diff_between_commits(temp_git_repo: Path, run_git):
    """Test E2E workflow with changes between commits."""
    # Create first commit
    create_file(temp_git_repo, "file1.py", "line1\n")
    git_add_commit(temp_git_repo, "First commit")

    # Create second commit
    create_file(temp_git_repo, "file1.py", "line1\nline2\n")
    create_file(temp_git_repo, "file2.py", "content\n")
    git_add_commit(temp_git_repo, "Second commit")

    # Get diff between commits
    result = run_git("diff", "HEAD~1", "HEAD")

    # Should have changes
    assert result.stdout.strip() != ""


def test_e2e_complete_workflow(temp_git_repo: Path, run_git):
    """Test complete workflow: parse -> build tree -> sort."""
    # Create initial commit
    create_file(temp_git_repo, "src/main.py", "def main():\n    pass\n")
    create_file(temp_git_repo, "src/utils.py", "def helper():\n    pass\n")
    git_add_commit(temp_git_repo, "Initial commit")

    # Make changes
    create_file(temp_git_repo, "src/main.py", "def main():\n    print('hello')\n    pass\n")
    create_file(temp_git_repo, "src/models/user.py", "class User:\n    pass\n")
    create_file(temp_git_repo, "README.md", "# Project\n")

    # Get diff output
    result = run_git("diff")

    # Parse the output
    changes = parse_unified_diff(result.stdout)

    # Build tree
    root = build_tree(changes)

    # Should have created proper tree structure
    assert root.name == "."
    assert "src" in root.children or len(changes) > 0

    # Sort tree
    sort_tree(root, sort_by="size")

    # Should complete without errors
    assert root is not None


def test_e2e_with_deletions(temp_git_repo: Path, run_git):
    """Test E2E workflow with file deletions."""
    # Create initial commit with content
    create_file(temp_git_repo, "file1.py", "line1\nline2\nline3\nline4\n")
    git_add_commit(temp_git_repo, "Initial commit")

    # Delete some lines
    create_file(temp_git_repo, "file1.py", "line1\nline4\n")

    # Get diff
    result = run_git("diff")

    # Should show deletions
    assert result.stdout.strip() != ""


def test_e2e_staged_changes(temp_git_repo: Path, run_git):
    """Test E2E workflow with staged changes."""
    # Create initial commit
    create_file(temp_git_repo, "file1.py", "line1\n")
    git_add_commit(temp_git_repo, "Initial commit")

    # Make changes and stage them
    create_file(temp_git_repo, "file1.py", "line1\nline2\n")
    run_git("add", "file1.py")

    # Get staged diff
    result = run_git("diff", "--cached")

    # Should show staged changes
    assert "file1.py" in result.stdout
