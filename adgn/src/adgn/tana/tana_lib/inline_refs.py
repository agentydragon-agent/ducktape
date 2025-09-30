"""
Parsing and handling of inline references in Tana content.
"""

from __future__ import annotations

from collections.abc import Callable
import html
import json
import re
from typing import Any

# Regex patterns for inline references
NODE_SPAN_PATTERN = re.compile(r'<span data-inlineref-node="([^"]+)"></span>')
DATE_SPAN_PATTERN = re.compile(r'<span data-inlineref-date="([^"]+)"></span>')


def parse_inline_date(date_ref_data: str) -> str:
    """
    Parse a Tana inline date reference.

    Args:
        date_ref_data: The escaped JSON data from the date span

    Returns:
        ISO-formatted date string with timezone notation
    """
    data: dict[str, Any] = json.loads(html.unescape(date_ref_data))
    date_str: str = str(data["dateTimeString"])  # ensure precise type for mypy
    timezone: str = str(data.get("timezone", "")) if data.get("timezone", "") else ""

    # Check if it's a date-only value (no time component)
    # Date-only formats: YYYY, YYYY-MM, YYYY-MM-DD, YYYY-Www
    if "T" not in date_str and "/" not in date_str:
        # Date-only values don't include timezone
        return date_str
    if "/" in date_str and timezone:
        # Date range - need to add timezone to each date
        dates = date_str.split("/")
        return f"{dates[0]}[{timezone}]/{dates[1]}[{timezone}]"
    # Single DateTime value
    return f"{date_str}[{timezone}]" if timezone else date_str


def replace_inline_refs(
    text: str,
    node_replacer: Callable[[str], str] | None = None,
    date_replacer: Callable[[str], str] | None = None,
) -> str:
    """
    Replace inline references in text with custom formatting.

    Args:
        text: The text containing inline references
        node_replacer: Function to replace node references (takes node ID, returns replacement text)
        date_replacer: Function to replace date references (takes ISO date string, returns replacement text)

    Returns:
        Text with inline references replaced
    """
    if node_replacer:
        text = NODE_SPAN_PATTERN.sub(lambda m: node_replacer(m.group(1)), text)

    if date_replacer:

        def date_sub(m):
            iso_date = parse_inline_date(m.group(1))
            return date_replacer(iso_date)

        text = DATE_SPAN_PATTERN.sub(date_sub, text)

    return text


def find_inline_node_refs(text: str) -> list[str]:
    """
    Find all inline node references in text.

    Args:
        text: The text to search

    Returns:
        List of node IDs referenced in the text
    """
    return NODE_SPAN_PATTERN.findall(text)
