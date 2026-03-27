"""E2E tests for precommit_runner with real pre-commit hooks.

Sets up a temporary git repo with local pre-commit hooks and verifies that
run_on_file correctly identifies which hooks modified files vs just failed.

# Snapshot update workflow: see root AGENTS.md "Updating syrupy snapshots".
"""

import sys
from pathlib import Path
from textwrap import dedent

import pytest
import pytest_bazel
from more_itertools import one
from syrupy.assertion import SnapshotAssertion

from devinfra.claude.hook_config import PreCommitConfig
from devinfra.claude.hook_daemon.conftest import init_git_repo, write_precommit_config
from devinfra.claude.hook_daemon.post_tool_use import _format_check_result
from devinfra.claude.hook_daemon.precommit_runner import (
    HookFailedNotApplied,
    HookOutcome,
    HookPassed,
    HookWouldEdit,
    RunResult,
    run_on_file,
)

# Relative path used in _format_check_result to keep snapshots stable
# (avoids embedding tmp dir absolute paths).
_TEST_FILE = Path("test.py")


def _make_script(repo: Path, name: str, body: str) -> Path:
    script = repo / name
    script.write_text(f"#!{sys.executable}\n{dedent(body)}")
    script.chmod(0o755)
    return script


@pytest.fixture
def precommit_repo(tmp_path: Path) -> Path:
    """Git repo with three local hooks: fixer, checker, passthrough."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    # Hook 1: replaces 'foo' with 'bar', exits 1 on change
    _make_script(
        repo_path,
        "fixer.py",
        """\
        import sys
        from pathlib import Path

        changed = False
        for f in sys.argv[1:]:
            p = Path(f)
            content = p.read_text()
            new = content.replace("foo", "bar")
            if new != content:
                p.write_text(new)
                changed = True
        sys.exit(1 if changed else 0)
        """,
    )

    # Hook 2: exits 1 if file contains 'BANNED', never modifies
    _make_script(
        repo_path,
        "checker.py",
        """\
        import sys
        from pathlib import Path

        for f in sys.argv[1:]:
            if "BANNED" in Path(f).read_text():
                print(f"{f}: contains BANNED keyword")
                sys.exit(1)
        sys.exit(0)
        """,
    )

    # Hook 3: always passes
    _make_script(
        repo_path,
        "passthrough.py",
        """\
        import sys
        sys.exit(0)
        """,
    )

    write_precommit_config(
        repo_path,
        [
            {
                "id": "fixer",
                "name": "fixer (foo->bar)",
                "entry": f"{sys.executable} {repo_path / 'fixer.py'}",
                "language": "system",
                "pass_filenames": True,
            },
            {
                "id": "checker",
                "name": "checker (no BANNED)",
                "entry": f"{sys.executable} {repo_path / 'checker.py'}",
                "language": "system",
                "pass_filenames": True,
            },
            {
                "id": "passthrough",
                "name": "passthrough",
                "entry": f"{sys.executable} {repo_path / 'passthrough.py'}",
                "language": "system",
                "pass_filenames": True,
            },
        ],
    )

    init_git_repo(repo_path)

    return repo_path


def _hook_by_id(result: RunResult, hook_id: str) -> HookOutcome:
    """Find a hook outcome by ID."""
    return one(h for h in result.hooks if h.hook_id == hook_id)


def test_fixer_modifies_checker_fails(precommit_repo: Path, snapshot: SnapshotAssertion) -> None:
    """Fixer modifies file, checker fails without modifying — correct labels."""
    test_file = precommit_repo / "test.py"
    test_file.write_text("foo = 1  # BANNED\n")

    result = run_on_file(test_file, precommit_repo)

    assert isinstance(_hook_by_id(result, "fixer"), HookWouldEdit)
    assert isinstance(_hook_by_id(result, "checker"), HookFailedNotApplied)
    assert isinstance(_hook_by_id(result, "passthrough"), HookPassed)

    output = _format_check_result(result, _TEST_FILE, PreCommitConfig())
    assert output == snapshot


def test_only_checker_fails(precommit_repo: Path, snapshot: SnapshotAssertion) -> None:
    """No fixer trigger, only checker fails — single non-zero exit."""
    test_file = precommit_repo / "test.py"
    test_file.write_text("clean = 1  # BANNED\n")

    result = run_on_file(test_file, precommit_repo)

    assert isinstance(_hook_by_id(result, "fixer"), HookPassed)
    assert isinstance(_hook_by_id(result, "checker"), HookFailedNotApplied)
    assert isinstance(_hook_by_id(result, "passthrough"), HookPassed)

    output = _format_check_result(result, _TEST_FILE, PreCommitConfig())
    assert output == snapshot


def test_all_pass(precommit_repo: Path) -> None:
    """Clean file — all hooks pass."""
    test_file = precommit_repo / "test.py"
    test_file.write_text("clean = 1\n")

    result = run_on_file(test_file, precommit_repo)
    assert not result.has_issues


def test_binary_file_no_diff(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    """Binary files that hooks modify should not produce a diff."""
    repo_path = tmp_path / "binrepo"
    repo_path.mkdir()

    # Binary-safe fixer: replaces 0xAA with 0xBB using raw bytes
    _make_script(
        repo_path,
        "binfixer.py",
        """\
        import sys
        from pathlib import Path

        changed = False
        for f in sys.argv[1:]:
            p = Path(f)
            content = p.read_bytes()
            new = content.replace(b"\\xaa", b"\\xbb")
            if new != content:
                p.write_bytes(new)
                changed = True
        sys.exit(1 if changed else 0)
        """,
    )

    write_precommit_config(
        repo_path,
        [
            {
                "id": "binfixer",
                "name": "binfixer",
                "entry": f"{sys.executable} {repo_path / 'binfixer.py'}",
                "language": "system",
                "pass_filenames": True,
            }
        ],
    )
    init_git_repo(repo_path)

    test_file = repo_path / "test.bin"
    test_file.write_bytes(b"\x00\xaa\xff\xfe")

    result = run_on_file(test_file, repo_path)

    assert isinstance(_hook_by_id(result, "binfixer"), HookWouldEdit)
    assert result.report_only_diff == []
    # File should be restored to original
    assert test_file.read_bytes() == b"\x00\xaa\xff\xfe"

    output = _format_check_result(result, Path("test.bin"), PreCommitConfig())
    assert output == snapshot


def test_file_restored_after_run(precommit_repo: Path) -> None:
    """Original file content is restored after run_on_file returns."""
    test_file = precommit_repo / "test.py"
    original = "foo = 1\n"
    test_file.write_text(original)

    result = run_on_file(test_file, precommit_repo)

    # Fixer should have changed foo->bar, but file is restored
    assert result.has_issues
    assert test_file.read_text() == original


if __name__ == "__main__":
    pytest_bazel.main()
