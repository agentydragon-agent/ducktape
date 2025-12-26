"""Tests for null byte sanitization in tool results."""

from mcp import types as mcp_types

from agent_core.agent import _sanitize_mcp_result


def test_no_nulls_unchanged(text_content):
    result = mcp_types.CallToolResult(content=[text_content("clean")], isError=False)
    sanitized = _sanitize_mcp_result(result)
    assert sanitized.content == result.content


def test_nulls_in_text(text_content):
    result = mcp_types.CallToolResult(content=[text_content("a\x00b\x00c")], isError=False)
    sanitized = _sanitize_mcp_result(result)
    first_item = sanitized.content[0]
    assert isinstance(first_item, mcp_types.TextContent)
    text = first_item.text
    assert text.startswith("NOTE: 2 null byte(s) removed")
    assert "abc" in text


def test_nulls_in_structured(text_content):
    result = mcp_types.CallToolResult(
        content=[text_content("output")], structuredContent={"k": "v\x00", "nested": {"d": "x\x00"}}, isError=False
    )
    sanitized = _sanitize_mcp_result(result)
    assert sanitized.structuredContent == {"k": "v", "nested": {"d": "x"}}
    first_item = sanitized.content[0]
    assert isinstance(first_item, mcp_types.TextContent)
    assert "NOTE: 2 null byte(s) removed" in first_item.text


def test_empty_content_nulls_in_structured():
    result = mcp_types.CallToolResult(content=[], structuredContent={"a": "b\x00"}, isError=False)
    sanitized = _sanitize_mcp_result(result)
    assert len(sanitized.content) == 1
    first_item = sanitized.content[0]
    assert isinstance(first_item, mcp_types.TextContent)
    assert first_item.text.startswith("NOTE: 1 null byte(s) removed")


def test_prepends_to_first_text_block(text_content):
    result = mcp_types.CallToolResult(content=[text_content("a\x00"), text_content("b\x00")], isError=False)
    sanitized = _sanitize_mcp_result(result)
    first_item = sanitized.content[0]
    second_item = sanitized.content[1]
    assert isinstance(first_item, mcp_types.TextContent)
    assert isinstance(second_item, mcp_types.TextContent)
    assert first_item.text.startswith("NOTE: 2 null byte(s) removed")
    assert second_item.text == "b"


def test_inserts_before_non_text_first_block(text_content):
    result = mcp_types.CallToolResult(
        content=[mcp_types.ImageContent(type="image", data="data", mimeType="image/png"), text_content("a\x00")],
        isError=False,
    )
    sanitized = _sanitize_mcp_result(result)
    assert len(sanitized.content) == 3
    first_item = sanitized.content[0]
    assert isinstance(first_item, mcp_types.TextContent)
    assert first_item.text.startswith("NOTE: 1 null byte(s) removed")
    assert isinstance(sanitized.content[1], mcp_types.ImageContent)


def test_nested_structures(text_content):
    result = mcp_types.CallToolResult(
        content=[text_content("x")], structuredContent={"a": {"b": {"c": ["x\x00", "y\x00"]}}}, isError=False
    )
    sanitized = _sanitize_mcp_result(result)
    assert sanitized.structuredContent == {"a": {"b": {"c": ["x", "y"]}}}


def test_preserves_error_and_meta(text_content):
    result = mcp_types.CallToolResult(content=[text_content("err\x00")], isError=True, _meta={"k": "v"})
    sanitized = _sanitize_mcp_result(result)
    assert sanitized.isError is True
    assert sanitized.meta == {"k": "v"}
