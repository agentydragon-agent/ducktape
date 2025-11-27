"""Reusable Hamcrest matchers for agent test assertions.

This module provides matchers for verifying agent behavior in tests.
WebSocket-specific infrastructure has been removed (MCP replaced WebSocket).
"""

from __future__ import annotations

from hamcrest import (
    any_of,
    assert_that,
    contains_string,
    equal_to,
    has_entries,
    has_item,
    has_items,
    has_properties,
    is_not,
    none,
)
from hamcrest.core.matcher import Matcher
import pytest

from adgn.agent.server.protocol import RunStatus

# ------------------------
# Deprecated WS helpers (stubs)
# ------------------------


def drain_until_match(*args, **kwargs):
    """DEPRECATED: WebSocket infrastructure removed. Use MCP-based test patterns."""
    pytest.skip("WebSocket infrastructure removed; use MCP-based test fixtures")


def is_ui_state_event(*args, **kwargs):
    """DEPRECATED: WebSocket infrastructure removed. Use MCP-based test patterns."""
    pytest.skip("WebSocket infrastructure removed; use MCP-based test fixtures")


def collect_payloads_until_finished(*args, **kwargs):
    """DEPRECATED: WebSocket infrastructure removed. Use MCP-based test patterns."""
    pytest.skip("WebSocket infrastructure removed; use MCP-based test fixtures")


def wait_for_accepted(*args, **kwargs):
    """DEPRECATED: WebSocket infrastructure removed. Use MCP-based test patterns."""
    pytest.skip("WebSocket infrastructure removed; use MCP-based test fixtures")


# ------------------------
# Hamcrest matcher helpers
# ------------------------


def has_finished_run():
    """Matcher: run_status with status == finished."""
    return has_properties(type="run_status", run_state=has_properties(status=RunStatus.FINISHED))


# ------------------------
# Hub WS (agents) matchers
# ------------------------


ACTIVE_RUN_SET = is_not(none())
ACTIVE_RUN_CLEARED = any_of(none(), equal_to(""))


def agent_status(agent_id: str, *, active_run_id: Matcher | None = None, live: bool | None = True):
    """Generic matcher for hub JSON agent_status.

    - agent_id: required id
    - live: constrain live flag (default True). Pass None to avoid asserting it.
    - active_run_id: Hamcrest matcher for active_run_id (e.g., ACTIVE_RUN_SET / ACTIVE_RUN_CLEARED)
    """
    data_kvs: dict[str, object] = {"id": agent_id}
    if live is not None:
        data_kvs["live"] = live
    if active_run_id is not None:
        data_kvs["active_run_id"] = active_run_id
    return has_entries(type="agent_status", data=has_entries(**data_kvs))


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


def assert_finished(payloads: list[object]):
    """Assert payloads include a finished run_status event."""
    assert_payloads_have(payloads, has_finished_run())


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
