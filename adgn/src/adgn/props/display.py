"""Display utilities for props CLI commands."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar
from uuid import UUID

from rich import box
from rich.console import Console
from rich.table import Table

# Display constants
SHORT_UUID_LENGTH = 8
SHORT_SHA_LENGTH = 6

JustifyMethod = Literal["left", "right", "center", "full", "default"]
T = TypeVar("T")
V = TypeVar("V")


def short_uuid(uuid: UUID) -> str:
    """Return shortened UUID for display (first 8 characters).

    Args:
        uuid: UUID to shorten

    Returns:
        First 8 characters of the UUID string (e.g., "a1b2c3d4")
    """
    return str(uuid)[:SHORT_UUID_LENGTH]


def short_sha(sha: str) -> str:
    """Return shortened SHA256 hash for display (first 6 characters).

    Args:
        sha: SHA256 hash string to shorten

    Returns:
        First 6 characters of the SHA string
    """
    return sha[:SHORT_SHA_LENGTH]


def ellipticize(text: str, max_len: int) -> str:
    """Truncate text and show remaining character count.

    Args:
        text: Text to truncate
        max_len: Maximum length before truncation

    Returns:
        Truncated string with "...(N more)" suffix if text exceeds max_len

    Example:
        >>> ellipticize("hello world this is long", 10)
        "hello w...(17 more)"
    """
    if len(text) <= max_len:
        return text
    remaining = len(text) - max_len
    return f"{text[:max_len]}...({remaining} more)"


def format_truncation_footer(total_count: int, displayed_count: int, item_name: str = "items") -> str:
    """Format a footer showing how many items were not displayed.

    Args:
        total_count: Total number of items available
        displayed_count: Number of items displayed
        item_name: Name of the items (e.g., "events", "files")

    Returns:
        Formatted string like "... (5 more events)" or empty string if all items shown

    Example:
        >>> format_truncation_footer(100, 20, "events")
        "... (80 more events)"
        >>> format_truncation_footer(5, 10, "items")
        ""
    """
    if total_count > displayed_count:
        remaining = total_count - displayed_count
        return f"... ({remaining} more {item_name})"
    return ""


def print_truncation_footer(
    print_fn: Any, total_count: int, displayed_count: int, item_name: str = "items", prefix: str = "\n"
) -> None:
    """Print a footer showing truncation if items were not fully displayed.

    Args:
        print_fn: Function to call for printing (e.g., console.print or print)
        total_count: Total number of items available
        displayed_count: Number of items displayed
        item_name: Name of the items (e.g., "events", "files")
        prefix: String to prepend to the footer (default: newline)

    Example:
        >>> from rich.console import Console
        >>> console = Console()
        >>> print_truncation_footer(console.print, 100, 20, "events")
        # Prints: "\n... (80 more events)"
    """
    footer = format_truncation_footer(total_count, displayed_count, item_name)
    if footer:
        print_fn(f"{prefix}{footer}")


@dataclass
class ColumnDef[T, V]:
    """Column definition for declarative table building.

    Args:
        name: Column header text
        accessor: Function to extract value from row object
        formatter: Optional function to format the value for display (default: str)
        width: Optional fixed column width
        justify: Text justification ("left", "right", "center")
        style: Optional Rich style string
    """

    name: str
    accessor: Callable[[T], V]
    formatter: Callable[[V], str] = str
    width: int | None = None
    justify: JustifyMethod = "left"
    style: str | None = None


def build_table_from_schema[T](
    rows: Sequence[T],
    columns: Sequence[ColumnDef[T, Any]],
    *,
    show_header: bool = True,
    box_style: box.Box = box.SIMPLE,
) -> Table:
    """Build a Rich table from column schema and data rows.

    Args:
        rows: Data objects to display
        columns: Column definitions
        show_header: Whether to show column headers
        box_style: Rich box style for table borders

    Returns:
        Configured Rich Table with data
    """
    table = Table(show_header=show_header, header_style="bold cyan", box=box_style)

    # Add columns from schema
    for col in columns:
        table.add_column(col.name, width=col.width, justify=col.justify, style=col.style)

    # Add rows
    for row in rows:
        values = [col.formatter(col.accessor(row)) for col in columns]
        table.add_row(*values)

    return table


def print_table_with_footer[T](
    console: Console,
    rows: Sequence[T],
    columns: Sequence[ColumnDef[T, Any]],
    *,
    show_header: bool = True,
    box_style: box.Box = box.SIMPLE,
    total_count: int | None = None,
    item_name: str = "items",
) -> None:
    """Build and print a table with optional truncation footer.

    Args:
        console: Rich console for printing
        rows: Data objects to display
        columns: Column definitions
        show_header: Whether to show column headers
        box_style: Rich box style for table borders
        total_count: Total number of items available (for footer). If None, no footer is shown.
        item_name: Name of items for footer (e.g., "events", "files")

    Example:
        >>> from rich.console import Console
        >>> console = Console()
        >>> data = [...]  # 20 items
        >>> columns = [ColumnDef("Name", lambda x: x.name)]
        >>> print_table_with_footer(console, data, columns, total_count=100, item_name="events")
        # Prints table and "... (80 more events)"
    """
    table = build_table_from_schema(rows, columns, show_header=show_header, box_style=box_style)
    console.print(table)
    if total_count is not None:
        print_truncation_footer(console.print, total_count, len(rows), item_name)
