"""Configuration for git-diff-tree rendering."""

from dataclasses import dataclass
from enum import StrEnum


class Column(StrEnum):
    """Available columns to display."""

    TREE = "tree"
    COUNTS = "counts"
    BARS = "bars"
    PERCENTAGES = "percentages"


class SortMode(StrEnum):
    """Sort mode for tree nodes."""

    SIZE = "size"
    ALPHA = "alpha"


def parse_columns(columns_str: str) -> list[Column]:
    """Parse comma-separated column names into Column enum values."""
    column_list = []
    for col in columns_str.split(","):
        col_stripped = col.strip()
        try:
            column_list.append(Column(col_stripped.lower()))
        except ValueError:
            valid_options = ", ".join(c.value for c in Column)
            raise ValueError(f"Unknown column '{col_stripped}'. Valid options: {valid_options}") from None
    return column_list


@dataclass
class RenderConfig:
    """Rendering configuration for diff trees."""

    columns: list[Column]
    bar_width: int = 20
    sort_by: SortMode = SortMode.SIZE
    max_depth: int | None = None

    @classmethod
    def default(cls) -> "RenderConfig":
        """Default configuration with all columns."""
        return cls(columns=[Column.TREE, Column.COUNTS, Column.BARS, Column.PERCENTAGES])
