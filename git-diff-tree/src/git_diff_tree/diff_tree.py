"""Render tree structure with rich formatting and progress bars."""

from rich.console import Console, ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .config import Column, RenderConfig
from .progress_bar import ProgressBar
from .tree import TreeNode


class DiffTree:
    """Renderable diff tree with progress bars and statistics."""

    def __init__(self, root: TreeNode, config: RenderConfig | None = None):
        self.root = root
        self.config = config or RenderConfig.default()

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Render as a Table with aligned tree structure and statistics."""
        max_additions, max_deletions = self._find_max_additions_deletions(self.root)
        max_changes = max_additions + max_deletions if (max_additions + max_deletions) > 0 else 1

        tree = self._build_tree_structure(self.root, depth=0)

        temp_console = Console(record=True, width=options.max_width or 80)
        temp_console.print(tree)
        segments = temp_console._record_buffer
        lines = list(Segment.split_lines(segments))

        tree_lines = []
        for line_segments in lines:
            text = Text()
            for segment in line_segments:
                if segment.text:
                    text.append(segment.text, style=segment.style)
            tree_lines.append(text)

        nodes_in_order = self._flatten_tree(self.root, depth=0)

        table = Table.grid(padding=0)

        for column in self.config.columns:
            if column == Column.TREE:
                table.add_column(justify="left")
            elif column == Column.COUNTS:
                table.add_column(justify="right")  # Additions (right-aligned)
                table.add_column(justify="left")   # Deletions (left-aligned)
            elif column == Column.BARS:
                table.add_column(justify="right")
                table.add_column(justify="left")
            elif column == Column.PERCENTAGES:
                table.add_column(justify="right")

        for tree_line, node in zip(tree_lines, nodes_in_order, strict=True):
            row = []
            for column in self.config.columns:
                if column == Column.TREE:
                    row.append(tree_line)
                elif column == Column.COUNTS:
                    additions_cell, deletions_cell = self._make_count_cells(node)
                    row.append(additions_cell)
                    row.append(deletions_cell)
                elif column == Column.BARS:
                    green_cell, red_cell = self._make_bar_cells(node, max_additions, max_deletions)
                    row.append(green_cell)
                    row.append(red_cell)
                elif column == Column.PERCENTAGES:
                    row.append(self._make_percentage_cell(node, max_changes))
            table.add_row(*row)

        yield table

    def _find_max_additions_deletions(self, node: TreeNode) -> tuple[int, int]:
        """Find maximum additions and deletions across all nodes."""
        max_additions = node.additions
        max_deletions = node.deletions

        for child in node.children.values():
            child_max_add, child_max_del = self._find_max_additions_deletions(child)
            max_additions = max(max_additions, child_max_add)
            max_deletions = max(max_deletions, child_max_del)

        return max_additions, max_deletions

    def _build_tree_structure(self, node: TreeNode, depth: int = 0) -> Tree:
        """Build Rich Tree with filenames only (no stats)."""
        name_color = "bold blue" if not node.is_file else "white"
        label = Text(node.name, style=name_color, overflow="ellipsis")
        tree = Tree(label)

        if (self.config.max_depth is None or depth < self.config.max_depth) and not node.is_file and node.children:
            for child in node.children.values():
                child_tree = self._build_tree_structure(child, depth + 1)
                tree.add(child_tree)

        return tree

    def _flatten_tree(self, node: TreeNode, depth: int = 0) -> list[TreeNode]:
        """Flatten tree into list of nodes in render order."""
        result = [node]

        if (self.config.max_depth is None or depth < self.config.max_depth) and not node.is_file and node.children:
            for child in node.children.values():
                result.extend(self._flatten_tree(child, depth + 1))

        return result

    def _make_count_cells(self, node: TreeNode) -> tuple[Text, Text]:
        """Create count cells with additions (right-aligned) and deletions (left-aligned)."""
        additions_cell = Text("  ")
        if node.additions > 0:
            additions_cell.append(f"+{node.additions}", style="green")

        deletions_cell = Text("")
        if node.deletions > 0:
            deletions_cell.append(f"-{node.deletions}", style="red")
        deletions_cell.append("  ")

        return additions_cell, deletions_cell

    def _make_bar_cells(self, node: TreeNode, max_additions: int, max_deletions: int) -> tuple[Text, Text]:
        """Create bar cells (green and red progress bars)."""
        # Additions use right-aligned bars
        green_bar = ProgressBar(
            value=node.additions,
            max_value=max_additions,
            width=self.config.bar_width,
            align="right",
            style="green",
            blocks=self.config.bar_right_blocks,  # RTL for additions
        )
        # Deletions use left-aligned bars
        red_bar = ProgressBar(
            value=node.deletions,
            max_value=max_deletions,
            width=self.config.bar_width,
            align="left",
            style="red",
            blocks=self.config.bar_left_blocks,  # LTR for deletions
        )

        green_cell = Text("  ")
        green_cell.append_text(green_bar.to_text())
        return green_cell, red_bar.to_text()

    def _make_percentage_cell(self, node: TreeNode, max_changes: int) -> Text:
        """Create percentage cell showing relative change size."""
        if max_changes > 0:
            percentage = (node.total_changes / max_changes) * 100
            pct_text = Text("  ")
            pct_text.append(f"{percentage:5.1f}%", style="cyan")
            return pct_text
        return Text("  ")
