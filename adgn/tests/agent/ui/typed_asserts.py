from __future__ import annotations

from hamcrest import assert_that, has_item, has_items, has_properties


def is_user_message(text: str | None = None):
    props = {"kind": "UserMessage"}
    if text is not None:
        props["text"] = text
    return has_properties(**props)


def is_assistant_markdown(md: str | None = None):
    props = {"kind": "AssistantMarkdown"}
    if md is not None:
        props["md"] = md
    return has_properties(**props)


def is_tool_item(tool: str | None = None, call_id: str | None = None):
    props = {"kind": "Tool"}
    if tool is not None:
        props["tool"] = tool
    if call_id is not None:
        props["call_id"] = call_id
    return has_properties(**props)


def assert_typed_items_have(items: list[object], *matchers):
    assert_that(items, has_items(*matchers))


def assert_typed_items_have_one(items: list[object], matcher):
    assert_that(items, has_item(matcher))
