import os

import pytest
from click.testing import CliRunner

from . import main


@pytest.fixture
def mock_config(monkeypatch):
    config = {
        "repos": {},
        "global": {
            "include": ["*.py"],
            "exclude": ["*.ignore"],
        },
        "strip_snippets": [
            {
                "type": "literal",
                "lines": "REMOVE THIS",
            },
        ],
    }
    monkeypatch.setattr(main, "load_config", lambda: config)


@pytest.fixture
def mock_repo(tmp_path):
    """
    Create a temporary "repo" with .py and .ignore files.
    Return the path to that repo directory.
    """
    dir = tmp_path / "myrepo"
    dir.mkdir()

    (dir / "file1.py").write_text("print('Hello')\nREMOVE THIS\n")
    (dir / "file2.py").write_text("def foo():\n    pass\n")
    (dir / "skipme.ignore").write_text("should exclude")

    return dir


def test_no_output(mock_config, mock_repo):
    """
    No -o => no dump content. We only expect stats.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        # cd into the mock_repo
        os.chdir(mock_repo)

        result = runner.invoke(main.main, [])
        assert result.exit_code == 0
        # We see "Files included: 2" if it included only file1.py + file2.py
        assert "Files included: 2" in result.output
        assert "skipme.ignore" not in result.output  # it's excluded
        # No "=== BEGIN DUMP ===" => no direct dump
        assert "=== BEGIN DUMP ===" not in result.output

        # The snippet "REMOVE THIS" should be removed from final
        # We can't see the final text though, because we didn't dump it.


def test_output_stdout(mock_config, mock_repo):
    """
    -o => dump to stdout.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.chdir(mock_repo)

        result = runner.invoke(main.main, ["-o"])
        assert result.exit_code == 0
        # Should see the big dump markers
        assert "=== BEGIN DUMP ===" in result.output
        assert "=== END DUMP ===" in result.output

        # Should have included content from file1.py, minus the snippet
        assert "print('Hello')" in result.output
        assert "REMOVE THIS" not in result.output

        # Stats
        assert "Files included: 2" in result.output


def test_output_file(mock_config, mock_repo, tmp_path):
    """
    -o somefile => writes to that file. We can read it back and confirm snippet removal.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.chdir(mock_repo)
        outpath = tmp_path / "dump_output.txt"

        result = runner.invoke(main.main, ["-o", str(outpath)])
        assert result.exit_code == 0
        assert f"Dump written to: {outpath}" in result.output

        # The script shouldn't have the big "=== BEGIN DUMP ===" in stdout
        assert "=== BEGIN DUMP ===" not in result.output

        # Check file contents
        written = outpath.read_text()
        assert "print('Hello')" in written
        assert "REMOVE THIS" not in written


def test_copy_flag(mock_config, mock_repo):
    """
    -c => tries to copy the dump to clipboard. If pyperclip not installed,
    we get a warning. Otherwise "Dump copied to clipboard."
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.chdir(mock_repo)

        # Also do -o so we actually produce a dump
        result = runner.invoke(main.main, ["-o", "--copy"])

        # The exit code might be 0 (success) or 0 with a note about pyperclip missing
        assert result.exit_code == 0
        # We either see "Dump copied to clipboard." or "pyperclip not installed"
        assert (
            "Dump copied to clipboard." in result.output
            or "pyperclip not installed" in result.output
        )
