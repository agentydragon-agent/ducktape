from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastmcp.client.client import Client
from fastmcp.server.server import has_resource_prefix
from mcp import types as mcp_types
from pydantic import TypeAdapter
from pydantic.networks import AnyUrl


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


async def read_text_json_typed[T](client: Client[Any], uri: AnyUrl | str, model: type[T] | Any) -> T:
    """Read a text JSON resource and parse it as the given Pydantic model/type.

    Args:
        client: FastMCP client instance
        uri: Resource URI (AnyUrl or string)
        model: Type (class, Union, Annotated, etc.) that TypeAdapter can handle

    Returns:
        Parsed model instance

    - Validates exactly one text part
    - Parses JSON into the provided model/type using TypeAdapter(model).validate_json
    - Accepts concrete types (type[T]) and type expressions (Union, Annotated, etc.)
    - Type inference works for concrete types; Union types require explicit annotation
    """
    # Convert str to AnyUrl if needed
    uri_obj: AnyUrl = AnyUrl(uri) if isinstance(uri, str) else uri
    contents = await client.read_resource(uri_obj)
    validated: T = TypeAdapter(model).validate_json(extract_single_text_content(contents))
    return validated


def derive_origin_server(uri: str, mount_names: Iterable[str]) -> str:
    """Find which mounted server owns the given resource URI.

    Uses FastMCP's path format (protocol://prefix/path).
    Raises ValueError if no server matches.
    """
    sorted_names = sorted(mount_names)
    for name in sorted_names:
        if has_resource_prefix(uri, name):
            return name

    raise ValueError(f"Could not derive origin server for URI {uri!r}. Available servers: {sorted_names}")
