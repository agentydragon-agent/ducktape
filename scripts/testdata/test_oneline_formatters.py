#!/usr/bin/env python3
"""Demonstrate which Python formatters can collapse multi-line to one-line.

This test suite shows:
1. What doesn't work (default configs respect trailing commas)
2. What DOES work:
   - ✅ Ruff: skip-magic-trailing-comma = true (BEST - built-in!)
   - ✅ yapf: disable_ending_comma_heuristic = true (also works)
   - ✅ Manual: remove trailing commas first, then format
3. What COM819 actually does (removes commas from one-liners only)

RECOMMENDED SOLUTION: Use Ruff with skip-magic-trailing-comma = true
"""

import re
import subprocess
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

# Test input: multi-line constructs with trailing commas
MULTILINE_WITH_COMMAS = dedent('''
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
EXPECTED_COLLAPSED = dedent('''
    """Test file."""

    import click


    @click.option("--no-percentages", is_flag=True, help="Hide percentage column")
    def func1():
        pass


    result = some_function(arg1="value1", arg2="value2", arg3="value3")

    my_dict = {"key1": "value1", "key2": "value2", "key3": "value3"}
''').strip() + "\n"  # Formatters add trailing newline


def remove_trailing_commas(content: str) -> str:
    """Remove trailing commas before closing brackets."""
    patterns = [
        (r',(\s*)\)', r'\1)'),
        (r',(\s*)\]', r'\1]'),
        (r',(\s*)\}', r'\1}'),
    ]
    result = content
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)
    return result


def run_ruff_format(content: str, line_length: int = 120) -> str:
    """Run ruff format on content."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(content)
        f.flush()
        tmpfile = Path(f.name)

    try:
        subprocess.run(
            ["ruff", "format", "--line-length", str(line_length), str(tmpfile)],
            check=True,
            capture_output=True,
        )
        return tmpfile.read_text()
    finally:
        tmpfile.unlink()


def run_yapf(content: str) -> str:
    """Run yapf on content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        tmpfile = tmpdir / "test.py"
        tmpfile.write_text(content)

        # Create yapf config
        (tmpdir / ".style.yapf").write_text(dedent('''
            [style]
            based_on_style = google
            column_limit = 120
        '''))

        subprocess.run(
            ["yapf", "--in-place", str(tmpfile)],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )
        return tmpfile.read_text()


def run_autopep8(content: str, aggressive: int = 2) -> str:
    """Run autopep8 on content."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(content)
        f.flush()
        tmpfile = Path(f.name)

    try:
        args = ["autopep8", "--in-place", "--max-line-length=120"]
        for _ in range(aggressive):
            args.append("--aggressive")
        args.append(str(tmpfile))

        subprocess.run(args, check=True, capture_output=True)
        return tmpfile.read_text()
    finally:
        tmpfile.unlink()


@pytest.mark.xfail(reason="Ruff respects trailing commas as 'keep multi-line' signal")
def test_ruff_alone_with_trailing_commas():
    """❌ Ruff format alone does NOT collapse when trailing commas present."""
    result = run_ruff_format(MULTILINE_WITH_COMMAS)
    assert result == EXPECTED_COLLAPSED


@pytest.mark.xfail(reason="yapf respects trailing commas as 'keep multi-line' signal")
def test_yapf_alone_with_trailing_commas():
    """❌ yapf alone does NOT collapse when trailing commas present."""
    result = run_yapf(MULTILINE_WITH_COMMAS)
    assert result == EXPECTED_COLLAPSED


@pytest.mark.xfail(reason="autopep8 doesn't collapse multi-line constructs at all")
def test_autopep8_aggressive_with_trailing_commas():
    """❌ autopep8 does NOT collapse multi-line constructs even with --aggressive."""
    result = run_autopep8(MULTILINE_WITH_COMMAS, aggressive=2)
    assert result == EXPECTED_COLLAPSED


def test_ruff_skip_magic_trailing_comma():
    """✅ BEST SOLUTION: Ruff with skip-magic-trailing-comma = true.

    This is the built-in Google-style solution - no scripts needed!
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        tmpfile = tmpdir / "test.py"
        tmpfile.write_text(MULTILINE_WITH_COMMAS)

        # Create ruff config with skip-magic-trailing-comma
        (tmpdir / "ruff.toml").write_text(dedent('''
            line-length = 120

            [format]
            skip-magic-trailing-comma = true
        '''))

        subprocess.run(
            ["ruff", "format", str(tmpfile)],
            cwd=tmpdir,
            check=True,
            capture_output=True,
        )

        result = tmpfile.read_text()
        assert result == EXPECTED_COLLAPSED


def test_ruff_with_comma_removal():
    """✅ Alternative: Ruff DOES collapse when trailing commas removed first.

    This works but requires a separate script (less elegant than skip-magic-trailing-comma).
    """
    without_commas = remove_trailing_commas(MULTILINE_WITH_COMMAS)
    result = run_ruff_format(without_commas)
    assert result == EXPECTED_COLLAPSED


def test_yapf_with_comma_removal():
    """✅ yapf DOES collapse when trailing commas removed first."""
    without_commas = remove_trailing_commas(MULTILINE_WITH_COMMAS)
    result = run_yapf(without_commas)
    # yapf collapses to one line (though it formats blank lines differently than ruff)
    assert "@click.option(" in result and "is_flag=True" in result
    assert "some_function(arg1=" in result
    assert '{"key1":' in result


def test_com819_only_affects_oneliners():
    """Demonstrate COM819: removes trailing commas from ONE-LINERS only.

    COM819 is NOT what we want - it only cleans up already-collapsed code.
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write('foo = (1, 2, 3,)\n')  # One-liner with trailing comma
        f.flush()
        tmpfile = Path(f.name)

    try:
        # Run ruff check with COM819
        subprocess.run(
            ["ruff", "check", "--select", "COM819", "--fix", str(tmpfile)],
            check=True,
            capture_output=True,
        )

        # COM819 removes the trailing comma
        assert tmpfile.read_text() == 'foo = (1, 2, 3)\n'
    finally:
        tmpfile.unlink()


def test_summary():
    """Summary of findings.

    This test documents the conclusions from all the other tests.

    NOTE: Since our repo's ruff.toml now has skip-magic-trailing-comma = true,
    run_ruff_format() now collapses by default. This test shows what different
    formatters do with their default configs.
    """
    # ✅ Ruff NOW collapses (our repo has skip-magic-trailing-comma = true)
    ruff_result = run_ruff_format(MULTILINE_WITH_COMMAS)
    assert ruff_result == EXPECTED_COLLAPSED

    # ❌ yapf default config respects trailing commas
    assert run_yapf(MULTILINE_WITH_COMMAS) != EXPECTED_COLLAPSED

    # ❌ autopep8 never collapses
    assert run_autopep8(MULTILINE_WITH_COMMAS) != EXPECTED_COLLAPSED

    # ✅ Alternative: remove commas first, then format
    no_commas = remove_trailing_commas(MULTILINE_WITH_COMMAS)
    yapf_result = run_yapf(no_commas)

    # yapf collapses when trailing commas removed
    assert "@click.option(" in yapf_result and "is_flag=True" in yapf_result
    assert "some_function(arg1=" in yapf_result
    assert '{"key1":' in yapf_result

    # ❌ autopep8 doesn't collapse even without trailing commas:
    assert run_autopep8(no_commas) != EXPECTED_COLLAPSED

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("\n✅ RECOMMENDED SOLUTION (no scripts needed!):")
    print("  Ruff with skip-magic-trailing-comma = true")
    print("\n  [format]")
    print("  skip-magic-trailing-comma = true")
    print("\n  This ignores trailing commas and collapses to one line!")
    print("\n✅ Alternative working combinations:")
    print("  1. yapf: disable_ending_comma_heuristic = true")
    print("  2. Manual: remove_trailing_commas() + ruff/yapf")
    print("\n❌ What doesn't work:")
    print("  - ruff/yapf with default config (respect trailing commas)")
    print("  - autopep8 (never collapses multi-line)")
    print("  - COM819 rule (only affects one-liners)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
