from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, TypeVar

from fastmcp.client.client import ClientSession
from fastmcp.server.server import has_resource_prefix
from mcp import types as mcp_types
from pydantic import TypeAdapter

from .urls import parse_any_url


def extract_single_text_content(res: list[mcp_types.TextResourceContents | mcp_types.BlobResourceContents]) -> str:
    """Return the single text part from a read_resource result or raise.

    - Requires exactly one TextResourceContents part.
    - Raises RuntimeError if zero or multiple text parts are present, or if any
      non-text part is present.
    """
    text_parts = [p for p in res if isinstance(p, mcp_types.TextResourceContents)]
    if any(isinstance(p, mcp_types.BlobResourceContents) for p in res):
        raise RuntimeError("expected a single text part, found blob content")
    if len(text_parts) != 1:
        raise RuntimeError(f"expected exactly one text part, found {len(text_parts)}")
    text: str | None = text_parts[0].text
    if text is None:
        raise RuntimeError("text content part missing text payload")
    return text


T = TypeVar("T")


async def read_text_json_typed[T](session: ClientSession, uri: str, model: type[T]) -> T:
    """Read a text JSON resource and parse it as the given Pydantic model/type.

    - Validates exactly one text part
    - Parses JSON into the provided model/type using TypeAdapter(model).validate_json
    """
    result = await session.read_resource(parse_any_url(uri))
    return TypeAdapter(model).validate_json(extract_single_text_content(result.contents))


async def read_text_json(session: ClientSession, uri: str) -> Any:
    """Read a text JSON resource and parse it to a Python dict."""
    return await read_text_json_typed(session, uri, dict[str, Any])


def derive_origin_server(
    uri: str, mount_names: Iterable[str], prefix_format: Literal["protocol", "path"] | None
) -> str:
    """Find which mounted server owns the given resource URI.

    Raises ValueError if no server matches.
    """
    sorted_names = sorted(mount_names)
    for name in sorted_names:
        if has_resource_prefix(uri, name, prefix_format):
            return name

    raise ValueError(f"Could not derive origin server for URI {uri!r}. Available servers: {sorted_names}")
