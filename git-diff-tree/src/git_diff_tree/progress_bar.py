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


class ProgressBar:
    """Progress bar with RTL or LTR alignment for diff statistics."""

    def __init__(
        self,
        value: int,
        max_value: int,
        width: int = 20,
        align: Literal["left", "right"] = "left",
        style: str = "default",
    ):
        self.value = value
        self.max_value = max_value
        self.width = width
        self.align = align
        self.style = style

    def to_text(self) -> Text:
        ratio = 0 if self.max_value == 0 else min(self.value / self.max_value, 1.0)
        filled_width = ratio * self.width
        full_blocks = int(filled_width)

        if self.align == "right":
            partial_block_index = int((filled_width - full_blocks) * (len(RIGHT_BLOCKS) - 1))
            bar_chars = ""
            if full_blocks < self.width and partial_block_index > 0:
                bar_chars = RIGHT_BLOCKS[partial_block_index]
            bar_chars += RIGHT_BLOCKS[-1] * full_blocks
            if self.value > 0 and not bar_chars:
                bar_chars = RIGHT_BLOCKS[1]
        else:
            partial_block_index = int((filled_width - full_blocks) * (len(LEFT_BLOCKS) - 1))
            bar_chars = LEFT_BLOCKS[-1] * full_blocks
            if full_blocks < self.width and partial_block_index > 0:
                bar_chars += LEFT_BLOCKS[partial_block_index]
            if self.value > 0 and not bar_chars:
                bar_chars = LEFT_BLOCKS[1]

        bar_chars = bar_chars.rjust(self.width) if self.align == "right" else bar_chars.ljust(self.width)
        return Text(bar_chars, style=self.style)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.to_text()
