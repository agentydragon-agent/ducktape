"""Progress bar renderables with RTL/LTR alignment support."""

from typing import Literal

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

# Unicode block characters for progress bars
# Left-growing blocks (for LTR bars): fills from left edge
LEFT_BLOCKS = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]

# Right-growing blocks (for RTL bars): fills from right edge
# Note: Unicode has limited right-block granularity, so we approximate
RIGHT_BLOCKS = [" ", "▕", "▕", "▐", "▐", "▐", "▉", "█", "█"]


def make_block_chars(
    full: str = "█",
    partials: str | list[str] | None = None,
    space: str = " ",
) -> list[str]:
    """
    Construct a block character sequence for progress bars.

    Args:
        full: Character to use for fully filled blocks
        partials: Character(s) to use for partial fills. Can be:
            - None: Use Unicode partial blocks ["▏", "▎", "▍", "▌", "▋", "▊", "▉"]
            - str: Single character repeated for all 7 partial positions
            - list[str]: Explicit list of 7 partial block characters
        space: Character to use for empty space

    Returns:
        List of 9 characters: [space, partial1, ..., partial7, full]

    Examples:
        >>> make_block_chars()  # Default Unicode blocks
        [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]
        >>> make_block_chars(full="-", partials="-")  # Simple dash for testing
        [" ", "-", "-", "-", "-", "-", "-", "-", "-"]
        >>> make_block_chars(full="X", partials="x")  # Different chars
        [" ", "x", "x", "x", "x", "x", "x", "x", "X"]
    """
    if partials is None:
        partials_list = ["▏", "▎", "▍", "▌", "▋", "▊", "▉"]
    elif isinstance(partials, str):
        partials_list = [partials] * 7
    else:
        if len(partials) != 7:
            raise ValueError(f"partials list must have exactly 7 elements, got {len(partials)}")
        partials_list = partials
    return [space] + partials_list + [full]


class ProgressBar:
    """Progress bar with RTL or LTR alignment for diff statistics."""

    def __init__(
        self,
        value: int,
        max_value: int,
        width: int = 20,
        align: Literal["left", "right"] = "left",
        style: str = "default",
        left_blocks: list[str] | None = None,
        right_blocks: list[str] | None = None,
    ):
        self.value = value
        self.max_value = max_value
        self.width = width
        self.align = align
        self.style = style
        self.left_blocks = left_blocks if left_blocks is not None else LEFT_BLOCKS
        self.right_blocks = right_blocks if right_blocks is not None else RIGHT_BLOCKS

    def to_text(self) -> Text:
        ratio = 0 if self.max_value == 0 else min(self.value / self.max_value, 1.0)
        filled_width = ratio * self.width
        full_blocks = int(filled_width)

        if self.align == "right":
            partial_block_index = int((filled_width - full_blocks) * (len(self.right_blocks) - 1))
            bar_chars = ""
            if full_blocks < self.width and partial_block_index > 0:
                bar_chars = self.right_blocks[partial_block_index]
            bar_chars += self.right_blocks[-1] * full_blocks
            if self.value > 0 and not bar_chars:
                bar_chars = self.right_blocks[1]
        else:
            partial_block_index = int((filled_width - full_blocks) * (len(self.left_blocks) - 1))
            bar_chars = self.left_blocks[-1] * full_blocks
            if full_blocks < self.width and partial_block_index > 0:
                bar_chars += self.left_blocks[partial_block_index]
            if self.value > 0 and not bar_chars:
                bar_chars = self.left_blocks[1]

        bar_chars = bar_chars.rjust(self.width) if self.align == "right" else bar_chars.ljust(self.width)
        return Text(bar_chars, style=self.style)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.to_text()
