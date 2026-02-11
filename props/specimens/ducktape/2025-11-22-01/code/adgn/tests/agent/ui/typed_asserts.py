from __future__ import annotations

from hamcrest import all_of, assert_that, has_item, has_items, has_properties, instance_of, is_not

from adgn.agent.server.state import ExecContent, ToolItem


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


def is_tool_item_typed(**props):
    """Matcher: ToolItem instance with optional property constraints.

    Composable matcher factory combining type checking with property assertions.
    Unlike is_tool_item which checks the 'kind' property, this checks the actual type.

    Example: is_tool_item_typed(decision=None)
             is_tool_item_typed(kind="Tool", decision="approve")
    """
    m = [instance_of(ToolItem)]
    if props:
        m.append(has_properties(**props))
    return all_of(*m)


def is_exec_content_typed(**props):
    """Matcher: ExecContent instance with optional property constraints.

    Composable matcher factory for ExecContent with type checking.
    Example: is_exec_content_typed(content_kind="Exec", stdout="ok", exit_code=0)
    """
    m = [instance_of(ExecContent)]
    if props:
        m.append(has_properties(**props))
    return all_of(*m)


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
