from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import partial
import os
from typing import Any

from hamcrest import (
    any_of,
    assert_that,
    contains_string,
    equal_to,
    has_entries,
    has_item,
    has_items,
    has_properties,
    instance_of,
    is_not,
    none,
)
from hamcrest.core.matcher import Matcher

from adgn.agent.server.protocol import (
    Accepted,
    Envelope,
    RunStatus,
    RunStatusEvt,
    ServerMessage,
    UiStateSnapshot,
    UiStateUpdated,
)

# ---- Tracing utilities -------------------------------------------------------


def _is_trace_enabled() -> bool:
    return os.getenv("ADGN_TEST_TRACE_WS", "0") in ("1", "true", "TRUE")


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _trace(name: str, msg: str) -> None:
    if _is_trace_enabled():
        print(f"[ws:{name} {_ts()}] {msg}")


# ---- Small mappers (deduplicated) -------------------------------------------


def _payload_mapper(e: Envelope) -> Any:
    return e.payload


def _identity_mapper(x: Any) -> Any:
    return x


def _short_payload(p: Any) -> str:
    try:
        t = getattr(p, "type", None)
        if t == "run_status":
            return f"run_status status={getattr(p.run_state, 'status', '?')}"
        if isinstance(p, UiStateSnapshot):
            return "ui_state_snapshot"
        if isinstance(p, UiStateUpdated):
            return "ui_state_updated"
        if t == "approval_pending":
            return f"approval_pending call_id={getattr(p, 'call_id', '?')}"
        if t == "approval_decision":
            return f"approval_decision call_id={getattr(p, 'call_id', '?')}"
        if t == "function_call_output":
            kind = getattr(p, "kind", None)
            return f"function_call_output kind={kind}"
        if t is not None:
            return str(t)
        # Fallback for dicts (hub JSON)
        if isinstance(p, dict):
            tp = p.get("type")
            if tp == "agent_status":
                d = p.get("data", {})
                return f"agent_status id={d.get('id')} live={d.get('live')} active_run_id={d.get('active_run_id')}"
            return str(tp or "json")
    except Exception:
        return str(type(p).__name__)
    return str(type(p).__name__)


def _fetch_envelope(ws):
    return Envelope.model_validate(ws.receive_json())


def drain(
    *,
    fetch: Callable[[], Any],
    until: Callable[[Any], bool] | None = None,
    match: Matcher | None = None,
    match_key: Callable[[Any], Any] | None = None,
    collect: Callable[[Any], Any] | None = None,
    limit: int = 200,
    name: str = "stream",
    trace: bool | None = None,
):
    """Generic drain of a pull-based stream.

    - Exactly one of `until` or `match` must be provided.
    - `match_key` maps source items before evaluation (e.g., Envelope → payload).
    - `collect` maps source items before appending to the result list.
    """
    if (until is None) == (match is None):
        raise ValueError("Provide exactly one of `until` or `match`")

    key = match_key or _identity_mapper
    collect_fn = collect or _identity_mapper

    out: list[Any] = []
    do_trace = _is_trace_enabled() if trace is None else bool(trace)
    for _ in range(limit):
        src = fetch()
        item = collect_fn(src)
        out.append(item)
        if do_trace:
            _trace(name, f"recv: {_short_payload(item)}")
        target = key(src)
        if match is not None:
            hit = match.matches(target)
        else:
            assert until is not None, "Either until or match must be provided"
            hit = bool(until(target))
        if hit:
            if do_trace:
                _trace(name, "predicate matched; stopping drain")
            break
    return out


def drain_until(
    ws,
    predicate: Callable[[Envelope], bool],
    *,
    limit: int = 200,
    mapper: Callable[[Envelope], Any] | None = None,
    name: str = "agent",
    trace: bool | None = None,
):
    core = partial(
        drain,
        fetch=partial(_fetch_envelope, ws),
        match_key=_identity_mapper,
        collect=(mapper or _payload_mapper),
        limit=limit,
        name=name,
        trace=trace,
    )
    return core(until=predicate)


def drain_until_match(
    ws,
    matcher: Matcher,
    *,
    limit: int = 200,
    mapper: Callable[[Envelope], Any] | None = None,
    name: str = "agent",
    trace: bool | None = None,
):
    core = partial(
        drain,
        fetch=partial(_fetch_envelope, ws),
        match_key=_payload_mapper,
        collect=(mapper or _payload_mapper),
        limit=limit,
        name=name,
        trace=trace,
    )
    return core(match=matcher)


def _fetch_json(ws):
    return ws.receive_json()


def drain_json(
    ws,
    *,
    until: Callable[[dict], bool] | None = None,
    match: Matcher | None = None,
    limit: int = 200,
    mapper: Callable[[dict], Any] | None = None,
    name: str = "hub",
    trace: bool | None = None,
):
    core = partial(
        drain,
        fetch=partial(_fetch_json, ws),
        match_key=_identity_mapper,
        collect=(mapper or _identity_mapper),
        limit=limit,
        name=name,
        trace=trace,
    )
    if match is not None and until is not None:
        raise ValueError("Provide exactly one of `until` or `match`")
    if match is not None:
        return core(match=match)
    return core(until=until)


def drain_json_until(
    ws,
    predicate: Callable[[dict], bool],
    *,
    limit: int = 200,
    mapper: Callable[[dict], Any] | None = None,
    name: str = "hub",
    trace: bool | None = None,
):
    return drain_json(ws, until=predicate, limit=limit, mapper=mapper, name=name, trace=trace)


def drain_json_until_match(
    ws,
    matcher: Matcher,
    *,
    limit: int = 200,
    mapper: Callable[[dict], Any] | None = None,
    name: str = "hub",
    trace: bool | None = None,
):
    return drain_json(ws, match=matcher, limit=limit, mapper=mapper, name=name, trace=trace)


def _drain_core(
    *,
    fetch: Callable[[], Any],
    match_pred: Callable[[Any], bool],
    mapper: Callable[[Any], Any],
    name: str,
    trace: bool | None,
    limit: int,
):
    out: list[Any] = []
    do_trace = _is_trace_enabled() if trace is None else bool(trace)
    for _ in range(limit):
        src = fetch()
        item = mapper(src)
        out.append(item)
        if do_trace:
            _trace(name, f"recv: {_short_payload(item)}")
        if match_pred(src):
            if do_trace:
                _trace(name, "predicate matched; stopping drain")
            break
    return out


def collect_payloads_until_finished(ws, *, limit: int = 200):
    """Collect payloads until finished (thin wrapper over drain_until)."""
    return drain_until(
        ws,
        lambda e: isinstance(e.payload, RunStatusEvt) and e.payload.run_state.status == RunStatus.FINISHED,
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


def collect_payloads_until(ws, predicate: Callable[[Envelope], bool], *, limit: int = 200):
    """Collect payloads until predicate is True (thin wrapper over drain_until)."""
    return drain_until(ws, predicate, limit=limit, mapper=None)


def collect_envelopes_until_finished(ws, *, limit: int = 200):
    """Collect envelopes until finished (delegates to drain_until)."""
    return drain_until(
        ws,
        lambda e: isinstance(e.payload, RunStatusEvt) and e.payload.run_state.status == RunStatus.FINISHED,
        limit=limit,
        mapper=lambda e: e,
    )


def collect_payloads_until_finished_auto_approve(ws, *, limit: int = 200):
    """Collect typed payloads until finished, auto-approving on approval_pending."""
    payloads: list[ServerMessage] = []
    for _ in range(limit):
        env = Envelope.model_validate(ws.receive_json())
        p = env.payload
        if p.type == "approval_pending":
            ws.send_json({"type": "approve", "call_id": p.call_id})
            # Optionally include the pending event as well for assertion
            payloads.append(p)
            continue
        payloads.append(p)
        if p.type == "run_status" and p.run_state.status == RunStatus.FINISHED:
            break
    return payloads


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


def is_ui_state_event():
    """Matcher covering UiStateSnapshot/UiStateUpdated envelopes."""

    return any_of(instance_of(UiStateSnapshot), instance_of(UiStateUpdated))
