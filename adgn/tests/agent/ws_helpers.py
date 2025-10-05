from __future__ import annotations

from typing import Any, Callable

from hamcrest import (
    assert_that,
    contains_string,
    has_entries,
    has_item,
    has_items,
    has_properties,
)

from adgn.agent.server.protocol import Accepted, Envelope, RunStatusEvt


def drain_until(
    ws,
    predicate: Callable[[Envelope], bool],
    *,
    limit: int = 200,
    mapper: Callable[[Envelope], Any] | None = None,
):
    """General drain helper: read envelopes until predicate(envelope) is True.

    - mapper selects what to return for each envelope (default: payload)
    - returns a list of mapped items
    """
    if mapper is None:

        def mapper(e: Envelope) -> Any:  # default: payloads
            return e.payload

    out = []
    for _ in range(limit):
        env = Envelope.model_validate(ws.receive_json())
        out.append(mapper(env))
        if predicate(env):
            break
    return out


def collect_payloads_until_finished(ws, *, limit: int = 200):
    """Collect payloads until finished (thin wrapper over drain_until)."""
    return drain_until(
        ws,
        lambda e: isinstance(e.payload, RunStatusEvt) and e.payload.run_state.status == "finished",
        limit=limit,
        mapper=None,  # default mapper returns payloads
    )


def wait_for_accepted(ws, *, limit: int = 20) -> Envelope:
    """Read until an Accepted envelope or raise AssertionError if not seen."""
    for _ in range(limit):
        env = Envelope.model_validate(ws.receive_json())
        if isinstance(env.payload, Accepted):
            return env
    raise AssertionError("accepted not received")


def collect_payloads_until(
    ws,
    predicate: Callable[[Envelope], bool],
    *,
    limit: int = 200,
):
    """Collect payloads until predicate is True (thin wrapper over drain_until)."""
    return drain_until(ws, predicate, limit=limit, mapper=None)


def collect_envelopes_until_finished(ws, *, limit: int = 200):
    """Collect envelopes until finished (delegates to drain_until)."""
    return drain_until(
        ws,
        lambda e: isinstance(e.payload, RunStatusEvt) and e.payload.run_state.status == "finished",
        limit=limit,
        mapper=lambda e: e,
    )


def collect_payloads_until_finished_auto_approve(ws, *, limit: int = 200):
    """Collect typed payloads until finished, auto-approving on approval_pending."""
    payloads = []
    for _ in range(limit):
        env = Envelope.model_validate(ws.receive_json())
        p = env.payload
        if p.type == "approval_pending":
            ws.send_json({"type": "approve", "call_id": p.call_id})
            # Optionally include the pending event as well for assertion
            payloads.append(p)
            continue
        payloads.append(p)
        if p.type == "run_status" and p.run_state.status == "finished":
            break
    return payloads


# ------------------------
# Hamcrest matcher helpers
# ------------------------


def has_finished_run():
    """Matcher: run_status with status == finished."""
    return has_properties(type="run_status", run_state=has_properties(status="finished"))


def is_ui_message(content: str | None = None, mime: str | None = None):
    """Matcher: ui_message with optional content and mime constraints."""
    kwargs: dict[str, object] = {}
    if content is not None:
        kwargs["content"] = content
    if mime is not None:
        kwargs["mime"] = mime
    return has_properties(type="ui_message", message=has_properties(**kwargs))


def has_function_call_output_structured(**kvs):
    """Matcher: function_call_output with structuredContent containing kvs."""
    return has_entries(
        kind="function_call_output",
        result=has_entries(structuredContent=has_entries(**kvs)),
    )


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
        "result": has_entries(structuredContent=has_entries(**structured_kvs)),
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
        has_item(
            has_entries(
                kind="function_call_output",
                result=has_entries(structuredContent=has_entries(**kvs)),
            )
        ),
    )
