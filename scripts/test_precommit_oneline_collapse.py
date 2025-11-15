#!/usr/bin/env python3
"""Test pre-commit configurations for automatic one-line collapsing.

This test suite demonstrates which formatters can automatically collapse
multi-line constructs to one line, and what configuration is needed.
"""

import subprocess
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

# Test input: multi-line constructs with trailing commas
MULTILINE_INPUT = dedent('''
    """Test file."""
    import click

    @click.option(
        "--no-percentages",
        is_flag=True,
        help="Hide percentage column",
    )
    def func1():
        pass

    result = some_function(
        arg1="value1",
        arg2="value2",
        arg3="value3",
    )

    my_dict = {
        "key1": "value1",
        "key2": "value2",
        "key3": "value3",
    }
''').strip()

# Expected output: collapsed to one line
EXPECTED_ONELINE = dedent('''
    """Test file."""

    import click


    @click.option("--no-percentages", is_flag=True, help="Hide percentage column")
    def func1():
        pass


    result = some_function(arg1="value1", arg2="value2", arg3="value3")

    my_dict = {"key1": "value1", "key2": "value2", "key3": "value3"}
''').strip() + "\n"  # Ruff adds trailing newline


def create_git_repo(tmpdir: Path):
    """Initialize a git repo in tmpdir."""
    subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )


def run_precommit(tmpdir: Path) -> str:
    """Run pre-commit on all files and return the test.py content."""
    # Install pre-commit in a virtual environment
    venv_dir = tmpdir / ".venv"
    subprocess.run(
        ["python3", "-m", "venv", str(venv_dir)],
        check=True,
        capture_output=True,
    )

    pip = venv_dir / "bin" / "pip"
    precommit = venv_dir / "bin" / "pre-commit"

    # Install pre-commit
    subprocess.run(
        [str(pip), "install", "-q", "pre-commit"],
        check=True,
        capture_output=True,
    )

    # Install hooks
    subprocess.run(
        [str(precommit), "install"],
        cwd=tmpdir,
        check=True,
        capture_output=True,
    )

    # Run pre-commit (may fail, that's ok - we just want to see the result)
    subprocess.run(
        [str(precommit), "run", "--all-files"],
        cwd=tmpdir,
        capture_output=True,
    )

    return (tmpdir / "test.py").read_text()


@pytest.mark.xfail(reason="Ruff alone doesn't collapse multi-line with trailing commas")
def test_ruff_format_only():
    """Test ruff-format alone (WITHOUT trailing comma removal)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_git_repo(tmpdir)

        # Create test file
        test_file = tmpdir / "test.py"
        test_file.write_text(MULTILINE_INPUT)

        # Create ruff config
        (tmpdir / "ruff.toml").write_text(dedent('''
            line-length = 120
        '''))

        # Create pre-commit config (ruff-format only)
        (tmpdir / ".pre-commit-config.yaml").write_text(dedent('''
            repos:
              - repo: https://github.com/astral-sh/ruff-pre-commit
                rev: v0.11.10
                hooks:
                  - id: ruff-format
        '''))

        result = run_precommit(tmpdir)
        assert result == EXPECTED_ONELINE


@pytest.mark.xfail(reason="autopep8 doesn't collapse multi-line constructs")
def test_autopep8_aggressive():
    """Test autopep8 with --aggressive."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_git_repo(tmpdir)

        test_file = tmpdir / "test.py"
        test_file.write_text(MULTILINE_INPUT)

        (tmpdir / ".pre-commit-config.yaml").write_text(dedent('''
            repos:
              - repo: https://github.com/pre-commit/mirrors-autopep8
                rev: v2.0.4
                hooks:
                  - id: autopep8
                    args: [--in-place, --aggressive, --aggressive, --max-line-length=120]
        '''))

        result = run_precommit(tmpdir)
        assert result == EXPECTED_ONELINE


def test_ruff_with_comma_removal():
    """Test ruff-format WITH trailing comma removal hook.

    ✅ This approach WORKS - removes trailing commas first, then formats.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_git_repo(tmpdir)

        test_file = tmpdir / "test.py"
        test_file.write_text(MULTILINE_INPUT)

        # Create ruff config
        (tmpdir / "ruff.toml").write_text(dedent('''
            line-length = 120
        '''))

        # Create the trailing comma removal script
        script = tmpdir / "remove_commas.py"
        script.write_text(dedent('''
            #!/usr/bin/env python3
            import re
            import sys
            from pathlib import Path

            def remove_trailing_commas(content: str) -> str:
                patterns = [
                    (r',(\s*)\)', r'\\1)'),
                    (r',(\s*)\]', r'\\1]'),
                    (r',(\s*)\}', r'\\1}'),
                ]
                result = content
                for pattern, replacement in patterns:
                    result = re.sub(pattern, replacement, result)
                return result

            for file_path in sys.argv[1:]:
                path = Path(file_path)
                if path.suffix == '.py':
                    content = path.read_text()
                    new_content = remove_trailing_commas(content)
                    if content != new_content:
                        path.write_text(new_content)
        '''))
        script.chmod(0o755)

        # Create pre-commit config with comma removal BEFORE ruff-format
        (tmpdir / ".pre-commit-config.yaml").write_text(dedent('''
            repos:
              - repo: local
                hooks:
                  - id: remove-trailing-commas
                    name: remove-trailing-commas
                    entry: ./remove_commas.py
                    language: script
                    files: \\.py$
              - repo: https://github.com/astral-sh/ruff-pre-commit
                rev: v0.11.10
                hooks:
                  - id: ruff-format
        '''))

        result = run_precommit(tmpdir)
        assert result == EXPECTED_ONELINE


def test_yapf_with_comma_removal():
    """Test yapf WITH trailing comma removal hook.

    ✅ This approach also WORKS.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        create_git_repo(tmpdir)

        test_file = tmpdir / "test.py"
        test_file.write_text(MULTILINE_INPUT)

        # Create yapf config
        (tmpdir / ".style.yapf").write_text(dedent('''
            [style]
            based_on_style = google
            column_limit = 120
        '''))

        # Create the trailing comma removal script
        script = tmpdir / "remove_commas.py"
        script.write_text(dedent('''
            #!/usr/bin/env python3
            import re
            import sys
            from pathlib import Path

            def remove_trailing_commas(content: str) -> str:
                patterns = [
                    (r',(\s*)\)', r'\\1)'),
                    (r',(\s*)\]', r'\\1]'),
                    (r',(\s*)\}', r'\\1}'),
                ]
                result = content
                for pattern, replacement in patterns:
                    result = re.sub(pattern, replacement, result)
                return result

            for file_path in sys.argv[1:]:
                path = Path(file_path)
                if path.suffix == '.py':
                    content = path.read_text()
                    new_content = remove_trailing_commas(content)
                    if content != new_content:
                        path.write_text(new_content)
        '''))
        script.chmod(0o755)

        # Create pre-commit config
        (tmpdir / ".pre-commit-config.yaml").write_text(dedent('''
            repos:
              - repo: local
                hooks:
                  - id: remove-trailing-commas
                    name: remove-trailing-commas
                    entry: ./remove_commas.py
                    language: script
                    files: \\.py$
              - repo: https://github.com/google/yapf
                rev: v0.40.2
                hooks:
                  - id: yapf
                    args: [--in-place]
        '''))

        result = run_precommit(tmpdir)
        assert result == EXPECTED_ONELINE


def test_com819_explanation():
    """Demonstrate what COM819 does (removes trailing commas from ONE-LINERS only).

    This is NOT what we want - COM819 only affects constructs already on one line.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # One-liner with trailing comma
        test_file = tmpdir / "test.py"
        test_file.write_text('foo = (1, 2, 3,)\n')

        # Run ruff check with COM819
        result = subprocess.run(
            ["ruff", "check", "--select", "COM819", "--fix", str(test_file)],
            capture_output=True,
            text=True,
        )

        # COM819 removes the trailing comma from the one-liner
        assert test_file.read_text() == 'foo = (1, 2, 3)\n'


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
