"""Render tree structure with rich formatting and progress bars."""

from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.segment import Segment
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .config import Column, RenderConfig
from .progress_bar import DEFAULT_LEFT_BLOCKS, DEFAULT_RIGHT_BLOCKS, ProgressBar
from .tree import TreeNode

# Cell padding between columns
CELL_PADDING = "  "


class DiffTree:
    """Renderable diff tree with progress bars and statistics."""

    def __init__(self, root: TreeNode, config: RenderConfig | None = None):
        self.root = root
        self.config = config or RenderConfig.default()

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Render as a Table with aligned tree structure and statistics."""
        # Get totals from root (which has aggregated stats from all children)
        total_additions = self.root.additions
        total_deletions = self.root.deletions
        total_changes = total_additions + total_deletions if (total_additions + total_deletions) > 0 else 1

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

        # Pre-compute count cells (used for both width calculation and rendering)
        count_cells = {}
        if Column.COUNTS in self.config.columns:
            for node in nodes_in_order:
                count_cells[id(node)] = self._make_count_cells(node)

        # Calculate proportional bar widths based on total additions/deletions
        green_width, red_width = self._calculate_proportional_bar_widths(
            tree_lines, options.max_width or 80, total_additions, total_deletions,
            nodes_in_order, count_cells
        )

        table = Table.grid(padding=(0, 1))

        for column in self.config.columns:
            if column == Column.TREE:
                table.add_column(justify="left", overflow="fold")
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
                    additions_cell, deletions_cell = count_cells[id(node)]
                    row.append(additions_cell)
                    row.append(deletions_cell)
                elif column == Column.BARS:
                    green_cell, red_cell = self._make_bar_cells(
                        node, total_additions, total_deletions, green_width, red_width
                    )
                    row.append(green_cell)
                    row.append(red_cell)
                elif column == Column.PERCENTAGES:
                    row.append(self._make_percentage_cell(node, total_changes))
            table.add_row(*row)

        yield table


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
        if node.is_binary:
            binary_cell = Text(CELL_PADDING)
            binary_cell.append("[Binary]", style="dim")
            return binary_cell, Text(CELL_PADDING)

        additions_cell = Text(CELL_PADDING)
        if node.additions > 0:
            additions_cell.append(f"+{node.additions}", style="green")

        deletions_cell = Text("")
        if node.deletions > 0:
            deletions_cell.append(f"-{node.deletions}", style="red")
        deletions_cell.append(CELL_PADDING)

        return additions_cell, deletions_cell

    def _calculate_proportional_bar_widths(
        self, tree_lines: list[Text], terminal_width: int,
        total_additions: int, total_deletions: int, nodes: list[TreeNode],
        count_cells: dict[int, tuple[Text, Text]]
    ) -> tuple[int, int]:
        """Calculate proportional bar widths based on total additions/deletions ratio."""
        if Column.BARS not in self.config.columns:
            return 0, 0

        # Create a temporary console for measuring renderables
        temp_console = Console()

        # Find maximum tree width
        max_tree_width = max(
            (Measurement.get(temp_console, temp_console.options, line).maximum for line in tree_lines),
            default=0
        )

        # Calculate actual widths for other columns by measuring rendered content
        other_width = max_tree_width

        if Column.COUNTS in self.config.columns:
            # Find max width of additions and deletions cells
            max_additions_width = 0
            max_deletions_width = 0
            for node in nodes:
                add_cell, del_cell = count_cells[id(node)]
                max_additions_width = max(
                    max_additions_width,
                    Measurement.get(temp_console, temp_console.options, add_cell).maximum
                )
                max_deletions_width = max(
                    max_deletions_width,
                    Measurement.get(temp_console, temp_console.options, del_cell).maximum
                )
            other_width += max_additions_width + max_deletions_width

        if Column.PERCENTAGES in self.config.columns:
            # Percentage is always formatted as "  XXX.X%" (8 chars max)
            other_width += 8

        # Account for table padding (padding=(0, 1) adds 2 spaces per column)
        num_columns = sum([
            1 if Column.TREE in self.config.columns else 0,
            2 if Column.COUNTS in self.config.columns else 0,  # 2 cells
            2 if Column.BARS in self.config.columns else 0,    # 2 cells
            1 if Column.PERCENTAGES in self.config.columns else 0,
        ])
        padding_width = num_columns * 2  # 1 space on each side of each column
        other_width += padding_width

        # Calculate total available space for bars
        total_bar_space = terminal_width - other_width
        total_changes = total_additions + total_deletions

        # Handle edge case: no changes
        if total_changes == 0:
            half_space = max(total_bar_space // 2, 10)
            return half_space, half_space

        # Calculate proportional widths based on ratio of additions to deletions
        green_ratio = total_additions / total_changes
        green_width = max(int(total_bar_space * green_ratio), 10)
        red_width = max(total_bar_space - green_width, 10)

        # Apply maximum width if configured
        if self.config.bar_width:
            green_width = min(green_width, self.config.bar_width)
            red_width = min(red_width, self.config.bar_width)

        return green_width, red_width

    def _make_bar_cells(
        self, node: TreeNode, total_additions: int, total_deletions: int,
        green_width: int, red_width: int
    ) -> tuple[Text, Text]:
        """Create bar cells with proportional widths (green and red progress bars)."""
        if node.is_binary:
            return Text(CELL_PADDING), Text("")

        green_bar = ProgressBar(
            value=node.additions,
            max_value=total_additions if total_additions > 0 else 1,
            width=green_width,
            blocks=self.config.bar_right_blocks or DEFAULT_RIGHT_BLOCKS,
            align="right",
            style="green",
        )
        red_bar = ProgressBar(
            value=node.deletions,
            max_value=total_deletions if total_deletions > 0 else 1,
            width=red_width,
            blocks=self.config.bar_left_blocks or DEFAULT_LEFT_BLOCKS,
            align="left",
            style="red",
        )

        green_cell = Text(CELL_PADDING)
        green_cell.append_text(green_bar.to_text())
        red_cell = red_bar.to_text()
        return green_cell, red_cell

    def _make_percentage_cell(self, node: TreeNode, max_changes: int) -> Text:
        """Create percentage cell showing relative change size."""
        if node.is_binary or max_changes == 0:
            return Text(CELL_PADDING)

        ratio = node.total_changes / max_changes
        pct_text = Text(CELL_PADDING)
        pct_text.append(f"{ratio:>6.1%}", style="cyan")
        return pct_text
