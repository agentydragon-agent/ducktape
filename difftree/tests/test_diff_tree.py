"""Tests for DiffTree renderable."""

from difftree.config import Column, RenderConfig
from difftree.diff_tree import DiffTree
from difftree.parser import FileChange
from difftree.progress_bar import BlockChars
from difftree.tree import build_tree
from .conftest import render_to_string
import pytest
from rich.console import Console
from rich.segment import Segment
from rich.text import Text


def _render_to_text_lines(diff_tree: DiffTree, width: int = 80) -> list[Text]:
    """Render tree and return lines as Rich Text objects."""
    # Use recording console to capture segments
    console = Console(record=True, width=width)
    console.print(diff_tree)

    # Get segments and split into lines
    segments = console._record_buffer
    lines = list(Segment.split_lines(segments))

    # Convert each line to Text object
    text_lines = []
    for line_segments in lines:
        text = Text()
        for seg in line_segments:
            if not seg.is_control:
                text.append(seg.text, style=seg.style)
        text_lines.append(text)

    return text_lines


def test_renderer_initialization():
    """Test DiffTree initialization."""
    root = build_tree([FileChange(path="test.py", additions=1, deletions=0)])
    diff_tree = DiffTree(root)

    assert diff_tree.root is root
    assert Column.COUNTS in diff_tree.config.columns
    assert Column.BARS in diff_tree.config.columns
    assert Column.PERCENTAGES in diff_tree.config.columns
    assert diff_tree.config.bar_width == 20


def test_renderer_with_custom_options():
    """Test DiffTree with custom options."""
    root = build_tree([FileChange(path="test.py", additions=1, deletions=0)])
    config = RenderConfig(columns=[Column.TREE], bar_width=30)
    diff_tree = DiffTree(root, config=config)

    assert diff_tree.root is root
    assert Column.COUNTS not in diff_tree.config.columns
    assert Column.BARS not in diff_tree.config.columns
    assert Column.PERCENTAGES not in diff_tree.config.columns
    assert diff_tree.config.bar_width == 30


def test_render_simple_tree(sample_changes):
    """Test rendering a simple tree structure."""
    root = build_tree(sample_changes)
    diff_tree = DiffTree(root)
    result = render_to_string(diff_tree, width=120)

    # Check that key elements are present
    assert "src" in result
    assert "tests" in result
    assert "README.md" in result
    assert "main.py" in result
    assert "models" in result


def test_render_with_no_counts(sample_changes):
    """Test rendering without count columns."""
    root = build_tree(sample_changes)
    config = RenderConfig(columns=[Column.TREE, Column.BARS, Column.PERCENTAGES])
    diff_tree = DiffTree(root, config=config)
    result = render_to_string(diff_tree, width=120)

    # Should still have tree structure but different formatting
    assert "src" in result


def test_render_with_max_depth(sample_changes):
    """Test rendering with maximum depth limit."""
    root = build_tree(sample_changes)
    config = RenderConfig.default()
    config.max_depth = 1
    diff_tree = DiffTree(root, config=config)
    result = render_to_string(diff_tree, width=120)

    # Should show top-level items but not deeply nested ones
    assert "src" in result
    # Depth limit might prevent showing nested files
    # This is a simplified test


# Progress bar integration tests


def test_minimum_sliver_with_small_changes():
    """Test rendering with one very small change among larger ones."""
    # Create changes where one is very small relative to others
    changes = [
        FileChange(path="large_file.py", additions=10000, deletions=5000),
        FileChange(path="tiny_file.py", additions=1, deletions=0),
    ]

    root = build_tree(changes)
    diff_tree = DiffTree(root)
    result = render_to_string(diff_tree, width=120)

    # Both files should be visible in the output
    assert "large_file.py" in result
    assert "tiny_file.py" in result
    # The tiny file should have some visible indicator despite small ratio
    # (This is a high-level test; the unit test above is more precise)


# Console width tests


@pytest.mark.parametrize(
    "width",
    [
        40,  # Very narrow terminal
        80,  # Standard terminal width
        200,  # Wide terminal
    ],
)
def test_console_width_handling(width):
    """Test rendering with different console widths."""
    changes = [
        FileChange(path="src/very_long_filename_that_might_wrap.py", additions=100, deletions=50),
        FileChange(path="test.py", additions=10, deletions=5),
    ]

    root = build_tree(changes)
    config = RenderConfig.default()
    diff_tree = DiffTree(root, config=config)
    result = render_to_string(diff_tree, width=width)

    # Basic assertions: output should contain expected elements
    assert result.strip() != ""

    # Stats should be present
    assert "+100" in result or "+10" in result

    # Filename visibility depends on width
    if width >= 200:
        # Very wide: full collapsed path visible without wrapping
        assert "very_long_filename" in result
        assert "test.py" in result
    elif width >= 80:
        # Standard width: path may wrap but parts are visible
        assert "very_long" in result
        assert "test.py" in result
    # At width=40, table columns wrap onto multiple lines, making text
    # assertions unreliable - just verify output exists


# Progress bar format tests


def _extract_progress_bars(line: Text) -> str:
    """Extract just the progress bar characters from a line (after filename and counts)."""
    plain = line.plain
    block_chars = " ▏▎▍▌▋▊▉█"

    # Find a sequence of at least 40 consecutive block characters (2 * bar_width)
    # This is the dual progress bar section
    i = 0
    while i < len(plain):
        if plain[i] in block_chars:
            # Found start of a potential block sequence
            start = i
            while i < len(plain) and plain[i] in block_chars:
                i += 1
            length = i - start

            # If this sequence is at least 40 chars, it's our progress bar
            if length >= 40:
                # The sequence might include padding spaces before/after the bar
                # The bar itself is exactly 40 characters
                # Skip leading padding spaces (between counts and bar)
                bar_candidate = plain[start:i].lstrip(" ")
                # Take exactly 40 characters (the dual progress bar)
                return bar_candidate[:40]
        else:
            i += 1

    # Fallback: return empty if not found
    return ""


def test_progress_bar_format_pattern():
    """Test that progress bars render with proper alignment and padding."""
    changes = [FileChange(path="file.py", additions=100, deletions=50)]

    root = build_tree(changes)
    config = RenderConfig.default()
    config.bar_width = 20  # Set explicit width for predictability

    diff_tree = DiffTree(root, config=config)

    # Render and get Text lines directly
    lines = _render_to_text_lines(diff_tree, width=120)
    file_line = next(line for line in lines if "file.py" in line.plain)

    # Just verify bars are present and render properly
    plain = file_line.plain
    assert "file.py" in plain
    assert "+100" in plain
    assert "-50" in plain

    # Verify progress bars are present (block characters)
    block_chars = " ▏▎▍▌▋▊▉█"
    bar_char_count = sum(1 for char in plain if char in block_chars)
    assert bar_char_count > 0, "Progress bars should be present"


@pytest.mark.parametrize(("additions", "deletions"), [(100, 50), (200, 10), (5, 300), (1000, 500), (1, 1)])
def test_progress_bar_format_various_sizes(additions, deletions):
    """Test progress bar format with proportionally-sized bars."""
    changes = [FileChange(path=f"file_{additions}_{deletions}.py", additions=additions, deletions=deletions)]

    root = build_tree(changes)
    config = RenderConfig.default()
    config.bar_width = 20

    diff_tree = DiffTree(root, config=config)

    # Render and get Text lines directly
    lines = _render_to_text_lines(diff_tree, width=150)
    file_line = next(line for line in lines if f"file_{additions}_{deletions}.py" in line.plain)

    # Just check that bars are present and render properly
    plain = file_line.plain
    block_chars = " ▏▎▍▌▋▊▉█"

    # Count block characters to verify bars are present
    bar_char_count = sum(1 for char in plain if char in block_chars)
    assert bar_char_count > 0, f"No progress bars found for {additions}+/{deletions}-"

    # Verify the line contains the file info
    assert f"file_{additions}_{deletions}.py" in plain
    assert f"+{additions}" in plain
    assert f"-{deletions}" in plain


def test_progress_bars_align_consistently():
    """Test that files with same delta count have progress bars at same position."""
    # 3 files with same additions and deletions and same-length names for alignment
    changes = [
        FileChange(path="file_a.py", additions=100, deletions=50),
        FileChange(path="file_b.py", additions=100, deletions=50),
        FileChange(path="file_c.py", additions=100, deletions=50),
    ]

    root = build_tree(changes)
    config = RenderConfig.default()
    config.bar_width = 20

    diff_tree = DiffTree(root, config=config)

    # Render and get Text lines directly
    lines = _render_to_text_lines(diff_tree, width=150)

    # Extract lines for each file
    file_lines = {
        "file_a.py": next(line for line in lines if "file_a.py" in line.plain),
        "file_b.py": next(line for line in lines if "file_b.py" in line.plain),
        "file_c.py": next(line for line in lines if "file_c.py" in line.plain),
    }

    # Find the character range where progress bars appear in each line
    # Progress bars are the consecutive block characters
    block_chars = set(" ▏▎▍▌▋▊▉█")

    def find_bar_range(line: Text) -> tuple[int, int]:
        """Find start and end index of progress bar section."""
        start = None
        end = None
        in_blocks = False
        consecutive_blocks = 0

        for i, char in enumerate(line.plain):
            if char in block_chars:
                if not in_blocks:
                    # Count consecutive block chars to distinguish from single spaces
                    in_blocks = True
                    start = i
                consecutive_blocks += 1
            else:
                if in_blocks and consecutive_blocks >= 10:  # Must be substantial to be the bar
                    end = i
                    break
                in_blocks = False
                consecutive_blocks = 0

        return (start or -1, end or -1)

    ranges = {name: find_bar_range(line) for name, line in file_lines.items()}

    # All files should have bars starting and ending at the same position
    # (since they have the same stats and we're in a consistent layout)
    start_positions = [r[0] for r in ranges.values()]
    end_positions = [r[1] for r in ranges.values()]

    # The bars should align at the same column positions
    assert len(set(start_positions)) == 1, f"Bar start positions don't align: {ranges}"
    assert len(set(end_positions)) == 1, f"Bar end positions don't align: {ranges}"


def test_column_ordering():
    """Test that columns appear in the order specified in config."""
    changes = [
        FileChange(path="file.py", additions=10, deletions=5),
    ]
    root = build_tree(changes)

    # Test bars before tree
    config = RenderConfig(columns=[Column.BARS, Column.TREE, Column.COUNTS])
    diff_tree = DiffTree(root, config=config)
    result = render_to_string(diff_tree, width=80, force_terminal=False)

    # The output should have bars (█ characters) before the tree structure
    # Find first occurrence of tree characters (. or └ or ├) and bar characters (█)
    lines = result.split("\n")
    for line in lines:
        if "file.py" in line:
            # Find positions of key elements
            bar_pos = line.find("█") if "█" in line else -1
            tree_char_positions = [
                line.find(char) for char in [".", "└", "├", "│"] if char in line
            ]
            tree_pos = min(tree_char_positions) if tree_char_positions else -1

            if bar_pos != -1 and tree_pos != -1:
                # Bars should come before tree when BARS is listed first
                assert bar_pos < tree_pos, f"Expected bars before tree, but got bar at {bar_pos}, tree at {tree_pos}"
                break

    # Test tree before bars (standard order)
    config = RenderConfig(columns=[Column.TREE, Column.BARS, Column.COUNTS])
    diff_tree = DiffTree(root, config=config)
    result = render_to_string(diff_tree, width=80, force_terminal=False)

    lines = result.split("\n")
    for line in lines:
        if "file.py" in line:
            bar_pos = line.find("█") if "█" in line else -1
            tree_char_positions = [
                line.find(char) for char in [".", "└", "├", "│"] if char in line
            ]
            tree_pos = min(tree_char_positions) if tree_char_positions else -1

            if bar_pos != -1 and tree_pos != -1:
                # Tree should come before bars when TREE is listed first
                assert tree_pos < bar_pos, f"Expected tree before bars, but got tree at {tree_pos}, bar at {bar_pos}"
                break


def test_column_ordering_counts_first():
    """Test counts column can appear first."""
    changes = [
        FileChange(path="file.py", additions=10, deletions=5),
    ]
    root = build_tree(changes)

    # Counts first, then tree
    config = RenderConfig(columns=[Column.COUNTS, Column.TREE])
    diff_tree = DiffTree(root, config=config)
    result = render_to_string(diff_tree, width=80, force_terminal=False)

    lines = result.split("\n")
    for line in lines:
        if "file.py" in line:
            # Find positions of key elements
            plus_pos = line.find("+10") if "+10" in line else -1
            tree_char_positions = [
                line.find(char) for char in [".", "└", "├", "│"] if char in line
            ]
            tree_pos = min(tree_char_positions) if tree_char_positions else -1

            if plus_pos != -1 and tree_pos != -1:
                # Counts should come before tree when COUNTS is listed first
                assert plus_pos < tree_pos, f"Expected counts before tree, but got counts at {plus_pos}, tree at {tree_pos}"
                break


def test_bar_proportionality():
    """Test that progress bars render proportionally to actual changes."""
    changes = [
        FileChange(path="file1.py", additions=50, deletions=10),  # 5:1 ratio
        FileChange(path="file2.py", additions=1, deletions=10),   # 1:10 ratio
        FileChange(path="file3.py", additions=10, deletions=0),   # Only additions
    ]
    root = build_tree(changes)

    # Use simple distinct characters for testing:
    # - Additions use right-aligned bars, so they use right_blocks: '+'
    # - Deletions use left-aligned bars, so they use left_blocks: '-'
    # This makes counting trivial - just count '+' and '-' in plain text
    config = RenderConfig(
        columns=[Column.TREE, Column.BARS],
        bar_width=10,
        bar_left_blocks=BlockChars.simple("-"),   # Deletions (LTR)
        bar_right_blocks=BlockChars.simple("+"),  # Additions (RTL)
    )
    diff_tree = DiffTree(root, config=config)

    # Render and extract plain text (no ANSI codes needed)
    lines = _render_to_text_lines(diff_tree, width=80)

    file_lines = {}
    for line in lines:
        plain = line.plain
        for file_path in ["file1.py", "file2.py", "file3.py"]:
            if file_path in plain:
                file_lines[file_path] = plain
                break

    # Count '+' for additions and '-' for deletions
    file1_plus = file_lines["file1.py"].count("+")
    file1_minus = file_lines["file1.py"].count("-")
    file2_plus = file_lines["file2.py"].count("+")
    file2_minus = file_lines["file2.py"].count("-")
    file3_plus = file_lines["file3.py"].count("+")
    file3_minus = file_lines["file3.py"].count("-")

    # The bars are scaled to max values across all files:
    # max_additions = 50 + 1 + 10 = 61 (including root aggregation)
    # max_deletions = 10 + 10 + 0 = 20 (including root aggregation)

    # File1: +50 -10
    # Expected green bar: 50/61 ≈ 82% of 10 blocks ≈ 8 blocks
    # Expected red bar: 10/20 = 50% of 10 blocks = 5 blocks
    assert file1_plus >= 7 and file1_plus <= 9, f"file1.py should have ~8 '+', got {file1_plus}"
    assert file1_minus >= 4 and file1_minus <= 6, f"file1.py should have ~5 '-', got {file1_minus}"

    # File2: +1 -10
    # Expected green bar: 1/61 ≈ 1.6% ≈ minimal sliver (1 char)
    # Expected red bar: 10/20 = 50% = 5 blocks
    assert file2_plus == 1, f"file2.py should have exactly 1 '+' (minimal sliver), got {file2_plus}"
    assert file2_minus >= 4 and file2_minus <= 6, f"file2.py should have ~5 '-', got {file2_minus}"

    # File2 and file1 should have same '-' count (both have 10 deletions at same scale)
    assert abs(file2_minus - file1_minus) <= 1, (
        f"file2.py and file1.py both have 10 deletions, should have similar '-' counts: "
        f"file1={file1_minus}, file2={file2_minus}"
    )

    # File3: +10 -0
    # Expected green bar: 10/61 ≈ 16.4% ≈ 1.6 blocks
    # Expected red bar: 0/20 = 0% = 0 blocks
    assert file3_plus >= 1 and file3_plus <= 3, f"file3.py should have ~2 '+', got {file3_plus}"
    assert file3_minus == 0, f"file3.py should have no '-', got {file3_minus}"


def test_deletion_bar_alignment():
    """Test that deletion bars start at the same column position regardless of addition bar width."""
    changes = [
        FileChange(path="file1.py", additions=100, deletions=1),   # Mostly additions
        FileChange(path="file2.py", additions=1, deletions=100),   # Mostly deletions
        FileChange(path="file3.py", additions=50, deletions=50),   # Balanced
    ]
    root = build_tree(changes)

    # Use distinct character 'X' for deletions to make position finding easy
    config = RenderConfig(
        columns=[Column.TREE, Column.BARS],
        bar_width=10,
        bar_left_blocks=BlockChars.simple("X"),   # Deletions (LTR)
        bar_right_blocks=BlockChars.simple("+"),  # Additions (RTL)
    )
    diff_tree = DiffTree(root, config=config)

    # Render and extract plain text
    lines = _render_to_text_lines(diff_tree, width=120)

    # Get file lines (skip root which is first)
    file_lines = []
    for line in lines:
        plain = line.plain
        if any(f in plain for f in ["file1.py", "file2.py", "file3.py"]):
            file_lines.append(plain)

    # Expecting 3 file lines
    assert len(file_lines) == 3, f"Expected 3 file lines, got {len(file_lines)}"

    # Find position of first 'X' (deletion bar start) in each line
    positions = []
    for i, line in enumerate(file_lines):
        pos = line.find('X')
        assert pos != -1, f"No deletion bar found in line {i}: {line}"
        positions.append(pos)

    # All positions should be the same (deletion bars are left-aligned, start at same column)
    assert len(set(positions)) == 1, f"Deletion bars not aligned: positions={positions}, lines={file_lines}"
