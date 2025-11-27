from __future__ import annotations

from hamcrest import assert_that, has_item, has_items, has_properties, instance_of, is_not


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
    # ToolItem has tool_call with name and call_id inside
    tool_call_props = {}
    if tool is not None:
        tool_call_props["name"] = tool
    if call_id is not None:
        tool_call_props["call_id"] = call_id
    if tool_call_props:
        props["tool_call"] = has_properties(**tool_call_props)
    return has_properties(**props)


def assert_typed_items_have(items: list[object], *matchers):
    assert_that(items, has_items(*matchers))


def assert_typed_items_have_one(items: list[object], matcher):
    assert_that(items, has_item(matcher))


def assert_items_include_instances(items: list[object], *types: type[object]) -> None:
    """Assert that ``items`` contains instances of each provided type."""

    if not types:
        raise ValueError("at least one type is required")
    matchers = [instance_of(tp) for tp in types]
    assert_that(items, has_items(*matchers))


def assert_items_exclude_instance(items: list[object], typ: type[object]) -> None:
    """Assert that ``items`` contains no instance of ``typ``."""

    assert_that(items, is_not(has_item(instance_of(typ))))
