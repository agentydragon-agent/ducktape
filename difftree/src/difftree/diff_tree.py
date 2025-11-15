"""Render tree structure with rich formatting and progress bars."""

from rich.console import Console, ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .config import Column, RenderConfig
from .progress_bar import DEFAULT_LEFT_BLOCKS, DEFAULT_RIGHT_BLOCKS, ProgressBar
from .tree import TreeNode

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
                    # Apply dim style to tree decoration characters (box-drawing Unicode)
                    style = segment.style
                    if self._is_tree_decoration(segment.text):
                        # Combine existing style with dim
                        style = f"{segment.style} dim" if segment.style else "dim"
                    text.append(segment.text, style=style)
            tree_lines.append(text)

        nodes_in_order = self._flatten_tree(self.root, depth=0)

        table = Table.grid(padding=(0, 1))

        for column in self.config.columns:
            if column == Column.TREE:
                table.add_column(justify="left", overflow="fold")
            elif column == Column.COUNTS:
                table.add_column(justify="right")  # Additions (right-aligned)
                table.add_column(justify="left")   # Deletions (left-aligned)
            elif column == Column.BARS:
                # Use ratio to make bar columns proportionally sized
                table.add_column(justify="right", ratio=total_additions if total_additions > 0 else 1)
                table.add_column(justify="left", ratio=total_deletions if total_deletions > 0 else 1)
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
                    green_cell, red_cell = self._make_bar_cells(node, total_additions, total_deletions)
                    row.append(green_cell)
                    row.append(red_cell)
                elif column == Column.PERCENTAGES:
                    row.append(self._make_percentage_cell(node, total_changes))
            table.add_row(*row)

        yield table


    def _is_tree_decoration(self, text: str) -> bool:
        """Check if text consists only of tree decoration characters (box-drawing + spaces)."""
        if not text:
            return False
        # Box-drawing Unicode block is U+2500 to U+257F
        return all(c == ' ' or '\u2500' <= c <= '\u257f' for c in text)

    def _get_collapsed_path_and_node(self, node: TreeNode, depth: int) -> tuple[str, TreeNode, int]:
        """
        Get the collapsed path and final node for a single-child directory chain.

        Returns:
            Tuple of (collapsed_path, final_node, final_depth)
        """
        path_parts = []
        current = node
        current_depth = depth

        # Follow single-child chains until we hit a file, multi-child dir, or max depth
        while (
            not current.is_file
            and len(current.children) == 1
            and (self.config.max_depth is None or current_depth < self.config.max_depth)
        ):
            path_parts.append(current.name)
            current = next(iter(current.children.values()))
            current_depth += 1

        # Add the final node's name
        path_parts.append(current.name)

        collapsed_path = "/".join(path_parts)
        return collapsed_path, current, current_depth

    def _build_tree_structure(self, node: TreeNode, depth: int = 0) -> Tree:
        """Build Rich Tree with filenames only (no stats), collapsing single-child paths."""
        # Collect collapsed path for single-child directory chains
        collapsed_path, final_node, final_depth = self._get_collapsed_path_and_node(node, depth)

        name_color = "bold blue" if not final_node.is_file else "white"
        label = Text(collapsed_path, style=name_color, overflow="ellipsis")
        tree = Tree(label)

        if (self.config.max_depth is None or final_depth < self.config.max_depth) and not final_node.is_file and final_node.children:
            for child in final_node.children.values():
                child_tree = self._build_tree_structure(child, final_depth + 1)
                tree.add(child_tree)

        return tree

    def _flatten_tree(self, node: TreeNode, depth: int = 0) -> list[TreeNode]:
        """Flatten tree into list of nodes in render order, matching collapsed paths."""
        # Use the same collapsing logic as _build_tree_structure
        _, final_node, final_depth = self._get_collapsed_path_and_node(node, depth)

        result = [final_node]

        if (self.config.max_depth is None or final_depth < self.config.max_depth) and not final_node.is_file and final_node.children:
            for child in final_node.children.values():
                result.extend(self._flatten_tree(child, final_depth + 1))

        return result

    def _make_count_cells(self, node: TreeNode) -> tuple[Text, Text]:
        """Create count cells with additions (right-aligned) and deletions (left-aligned)."""
        if node.is_binary:
            return Text("[Binary]", style="dim"), Text("")

        additions_cell = Text()
        if node.additions > 0:
            additions_cell.append(f"+{node.additions}", style="green")

        deletions_cell = Text()
        if node.deletions > 0:
            deletions_cell.append(f"-{node.deletions}", style="red")

        return additions_cell, deletions_cell

    def _make_bar_cells(
        self, node: TreeNode, total_additions: int, total_deletions: int
    ) -> tuple[ProgressBar, ProgressBar]:
        """Create bar cells (green and red progress bars)."""
        if node.is_binary:
            # Return empty progress bars for binary files
            empty_green = ProgressBar(
                value=0,
                max_value=1,
                blocks=self.config.bar_right_blocks or DEFAULT_RIGHT_BLOCKS,
                align="right",
                style="green",
                max_width=0,
            )
            empty_red = ProgressBar(
                value=0,
                max_value=1,
                blocks=self.config.bar_left_blocks or DEFAULT_LEFT_BLOCKS,
                align="left",
                style="red",
                max_width=0,
            )
            return empty_green, empty_red

        green_bar = ProgressBar(
            value=node.additions,
            max_value=total_additions if total_additions > 0 else 1,
            blocks=self.config.bar_right_blocks or DEFAULT_RIGHT_BLOCKS,
            align="right",
            style="green",
            max_width=self.config.bar_width,
        )
        red_bar = ProgressBar(
            value=node.deletions,
            max_value=total_deletions if total_deletions > 0 else 1,
            blocks=self.config.bar_left_blocks or DEFAULT_LEFT_BLOCKS,
            align="left",
            style="red",
            max_width=self.config.bar_width,
        )

        return green_bar, red_bar

    def _make_percentage_cell(self, node: TreeNode, max_changes: int) -> Text:
        """Create percentage cell showing relative change size."""
        if node.is_binary or max_changes == 0:
            return Text("")

        ratio = node.total_changes / max_changes
        return Text(f"{ratio:>6.1%}", style="cyan")
