"""
HTML utilities for processing Tana exports.

Handles HTML content found in Tana JSON exports including:
- Inline references (nodes, dates)
- HTML formatting conversion
- Special span elements
"""

from __future__ import annotations

from collections.abc import Callable
import html
from html.parser import HTMLParser
from io import StringIO
import re

from .inline_refs import parse_inline_date
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
        # When starting an <em> immediately after **, suppress a single leading space in next data
        self._suppress_next_leading_space = False

    def handle_starttag(self, tag, attrs):
        self.tag_stack.append(tag)
        prev = self.output.getvalue()
        # If a formatting tag follows a comma without a space, insert one (",**" -> ", **")
        if prev.endswith(","):
            # Only add a space if not already present
            if not prev.endswith(", "):
                self.output.write(" ")
        if tag in ("b", "strong"):
            self.output.write("**")
        elif tag in ("i", "em"):
            # If italic starts right after bold, drop a single leading space from the next data chunk
            if prev.endswith("**"):
                self._suppress_next_leading_space = True
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
        # If a data chunk begins with a space immediately after opening a formatting marker,
        # drop that single space to avoid sequences like "** _italic_**".
        if data.startswith(" ") and self.output.getvalue().endswith(
            ("**", "_", "__", "<mark>", "<strike>", "<code>")
        ):
            data = data[1:]
        self._suppress_next_leading_space = False
        self.output.write(data)

    def get_markdown(self) -> str:
        return self.output.getvalue()


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
