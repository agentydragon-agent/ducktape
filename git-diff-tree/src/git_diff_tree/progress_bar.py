"""Progress bar renderables with RTL/LTR alignment support."""

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text


@dataclass(frozen=True)
class BlockChars:
    """Configuration for progress bar block characters.

    Represents the characters used to render progress bars with different fill levels:
    - full: Completely filled block
    - empty: Empty space
    - partials: Progressively fuller partial blocks
    """

    full: str
    empty: str = " "
    partials: tuple[str, ...] = field(default_factory=lambda: ("▏", "▎", "▍", "▌", "▋", "▊", "▉"))

    def __post_init__(self):
        """Validate block character configuration."""
        if len(self.partials) < 1:
            raise ValueError("partials must have at least 1 element")

    @classmethod
    def simple(cls, char: str, empty: str = " ") -> "BlockChars":
        """Create simple block chars using the same character for all fill levels.

        Args:
            char: Character to use for all filled states
            empty: Character to use for empty space

        Returns:
            BlockChars with single character for partials

        Example:
            >>> BlockChars.simple("-")  # All dashes
            BlockChars(full="-", empty=" ", partials=("-",))
        """
        return cls(full=char, empty=empty, partials=(char,))


# Default block character configurations
# Note: LTR (left-to-right) and RTL (right-to-left) alignments flip which side
# gets the filled blocks vs empty space:
# - LTR: filled blocks on left, empty space on right (e.g., "███    ")
# - RTL: empty space on left, filled blocks on right (e.g., "    ███")

# Left-growing blocks (for LTR alignment): filled portion grows from left edge
DEFAULT_LEFT_BLOCKS = BlockChars(
    full="█",
    empty=" ",
    partials=("▏", "▎", "▍", "▌", "▋", "▊", "▉"),
)

# Right-growing blocks (for RTL alignment): filled portion grows from right edge
# Note: Unicode has limited right-block granularity, so we approximate
DEFAULT_RIGHT_BLOCKS = BlockChars(
    full="█",
    empty=" ",
    partials=("▕", "▕", "▐", "▐", "▐", "▉", "█"),
)

class ProgressBar:
    """Progress bar with RTL or LTR alignment for diff statistics."""

    def __init__(
        self,
        value: int,
        max_value: int,
        width: int = 20,
        align: Literal["left", "right"] = "left",
        style: str = "default",
        blocks: BlockChars | None = None,
    ):
        self.value = value
        self.max_value = max_value
        self.width = width
        self.align = align
        self.style = style

        # Determine which blocks to use based on alignment
        if blocks is not None:
            self.blocks = blocks
        elif align == "left":
            self.blocks = DEFAULT_LEFT_BLOCKS
        else:  # align == "right"
            self.blocks = DEFAULT_RIGHT_BLOCKS

    def to_text(self) -> Text:
        ratio = 0 if self.max_value == 0 else min(self.value / self.max_value, 1.0)
        filled_width = ratio * self.width
        full_blocks = int(filled_width)

        # Calculate partial block index
        # The fractional part (0.0-1.0) is divided into (num_partials + 1) buckets:
        # - Bucket 0: no partial (empty)
        # - Buckets 1 to num_partials: use partials[0] through partials[num_partials-1]
        num_partials = len(self.blocks.partials)
        partial_block_index = int((filled_width - full_blocks) * (num_partials + 1))

        if self.align == "right":
            # RTL: build from right, growing leftward
            bar_chars = ""
            if full_blocks < self.width and partial_block_index > 0:
                # Map index 1..(num_partials) to partials[0..(num_partials-1)]
                bar_chars = self.blocks.partials[min(partial_block_index - 1, num_partials - 1)]
            # Add full blocks
            bar_chars += self.blocks.full * full_blocks
            # Ensure minimum sliver for non-zero values
            if self.value > 0 and not bar_chars:
                bar_chars = self.blocks.partials[0]
            # Right-align (pad left with empty)
            bar_chars = bar_chars.rjust(self.width, self.blocks.empty)
        else:
            # LTR: build from left, growing rightward
            bar_chars = self.blocks.full * full_blocks
            if full_blocks < self.width and partial_block_index > 0:
                # Map index 1..(num_partials) to partials[0..(num_partials-1)]
                bar_chars += self.blocks.partials[min(partial_block_index - 1, num_partials - 1)]
            # Ensure minimum sliver for non-zero values
            if self.value > 0 and not bar_chars:
                bar_chars = self.blocks.partials[0]
            # Left-align (pad right with empty)
            bar_chars = bar_chars.ljust(self.width, self.blocks.empty)

        return Text(bar_chars, style=self.style)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.to_text()
