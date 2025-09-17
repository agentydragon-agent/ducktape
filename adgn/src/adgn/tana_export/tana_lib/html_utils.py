"""
HTML utilities for processing Tana exports.

Handles HTML content found in Tana JSON exports including:
- Inline references (nodes, dates)
- HTML formatting conversion
- Special span elements
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from html.parser import HTMLParser
from io import StringIO
from typing import Any

from .types import NodeId

# Regex patterns for Tana-specific HTML elements
NODE_SPAN_PATTERN = re.compile(r'<span data-inlineref-node="([^"]+)"></span>')
DATE_SPAN_PATTERN = re.compile(r'<span data-inlineref-date="([^"]+)"></span>')


class HTMLToMarkdownParser(HTMLParser):
    """Convert HTML formatting to Markdown syntax."""

    def __init__(self):
        super().__init__()
        self.output = StringIO()
        self.tag_stack = []

    def handle_starttag(self, tag, attrs):
        self.tag_stack.append(tag)
        if tag in ("b", "strong"):
            self.output.write("**")
        elif tag in ("i", "em"):
            self.output.write("_")
        elif tag == "u":
            self.output.write("__")
        elif tag == "mark":
            self.output.write("<mark>")
        elif tag == "strike":
            self.output.write("<strike>")
        elif tag == "code":
            self.output.write("<code>")

    def handle_endtag(self, tag):
        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()
        if tag in ("b", "strong"):
            self.output.write("**")
        elif tag in ("i", "em"):
            self.output.write("_")
        elif tag == "u":
            self.output.write("__")
        elif tag == "mark":
            self.output.write("</mark>")
        elif tag == "strike":
            self.output.write("</strike>")
        elif tag == "code":
            self.output.write("</code>")

    def handle_data(self, data):
        self.output.write(data)

    def get_markdown(self) -> str:
        return self.output.getvalue()


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
    if ("T" not in date_str) and ("/" not in date_str):
        # Date-only values don't include timezone
        return date_str
    if "/" in date_str and timezone:
        # Date range - need to add timezone to each date
        dates = date_str.split("/")
        return f"{dates[0]}[{timezone}]/{dates[1]}[{timezone}]"
    # Single DateTime value
    return f"{date_str}[{timezone}]" if timezone else date_str


def html_to_markdown(html_text: str) -> str:
    """
    Convert HTML formatting to Markdown.

    Args:
        html_text: HTML-formatted text

    Returns:
        Markdown-formatted text
    """
    parser = HTMLToMarkdownParser()
    parser.feed(html_text)
    return parser.get_markdown()


def process_inline_refs(
    text: str,
    node_formatter: Callable[[str], str] | None = None,
    date_formatter: Callable[[str], str] | None = None,
    unescape: bool = True,
) -> str:
    """
    Process inline references in text with custom formatting.

    Args:
        text: The text containing inline references
        node_formatter: Function to format node references (takes node ID, returns formatted text)
        date_formatter: Function to format date references (takes ISO date string, returns formatted text)
        unescape: Whether to unescape HTML entities in the final result

    Returns:
        Text with inline references processed
    """
    # Process node references
    if node_formatter:
        text = NODE_SPAN_PATTERN.sub(lambda m: node_formatter(m.group(1)), text)

    # Process date references
    if date_formatter:

        def date_sub(m):
            iso_date = parse_inline_date(m.group(1))
            return date_formatter(iso_date)

        text = DATE_SPAN_PATTERN.sub(date_sub, text)

    # Unescape HTML entities if requested
    if unescape:
        text = html.unescape(text)

    return text


def find_inline_node_refs(text: str) -> list[NodeId]:
    """
    Find all inline node references in text.

    Args:
        text: The text to search

    Returns:
        List of node IDs referenced in the text
    """
    return [NodeId(match) for match in NODE_SPAN_PATTERN.findall(text)]


def find_inline_date_refs(text: str) -> list[str]:
    """
    Find all inline date references in text.

    Args:
        text: The text to search

    Returns:
        List of date reference data strings
    """
    return DATE_SPAN_PATTERN.findall(text)
