"""Reusable Hamcrest matchers for agent test assertions."""

from __future__ import annotations

from hamcrest import assert_that, contains_string, has_entries, has_item, has_items, has_properties

# ------------------------
# Hamcrest matcher helpers
# ------------------------


def is_ui_message(content: str | None = None, mime: str | None = None):
    """Matcher: ui_message with optional content and mime constraints."""
    kwargs: dict[str, object] = {}
    if content is not None:
        kwargs["content"] = content
    if mime is not None:
        kwargs["mime"] = mime
    return has_properties(type="ui_message", message=has_properties(**kwargs))


def has_function_call_output_structured(**kvs):
    """Matcher: function_call_output with structured_content containing kvs."""
    return has_entries(kind="function_call_output", result=has_entries(structured_content=has_entries(**kvs)))


def assert_payloads_have(payloads: list[object], *matchers):
    """Assert payloads contain all matchers using has_items."""
    assert_that(payloads, has_items(*matchers))


# Convenience alias for substring assertions
contains_err = contains_string


# ------------------------
# Higher-level payload matchers
# ------------------------


def is_function_call_output(call_id: str | None = None, **structured_kvs):
    """Matcher: payload is a function_call_output with optional call_id and structuredContent entries.

    Example: is_function_call_output(call_id="call_x", ok=True, echo="hello")
    """
    props: dict[str, object] = {
        "type": "function_call_output",
        "result": has_entries(structured_content=has_entries(**structured_kvs)),
    }
    if call_id is not None:
        props["call_id"] = call_id
    return has_properties(**props)


def is_function_call_output_end_turn(call_id: str | None = None):
    """Matcher: function_call_output for ui.end_turn (kind == EndTurn)."""
    return is_function_call_output(call_id=call_id, kind="EndTurn")


def assert_function_call_output_structured(records: list[dict], **kvs):
    """Assert that a RecordingHandler-style records list contains a function_call_output
    whose structuredContent matches the provided kv pairs.
    """
    assert_that(
        records,
        has_item(has_entries(kind="function_call_output", result=has_entries(structured_content=has_entries(**kvs)))),
    )
