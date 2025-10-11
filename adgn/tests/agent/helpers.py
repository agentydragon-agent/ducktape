from __future__ import annotations

import socket
import threading
import time
from typing import Any, Sequence

from hamcrest import all_of, assert_that, contains_string, has_item, has_properties
from uvicorn import Config, Server

from adgn.agent.server.protocol import ErrorCode, RunStatus, ServerMessage


def pick_free_port(host: str = "127.0.0.1") -> int:
    """Return an available TCP port on host by briefly binding a socket.

    Best-effort and race-tolerant for test usage.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, 0))
        return s.getsockname()[1]


def start_uvicorn_app(
    app: Any, *, host: str = "127.0.0.1", port: int | None = None, log_level: str = "info"
) -> dict[str, Any]:
    """Start a FastAPI app in a background thread with uvicorn.

    Returns a dict with base_url and stop() to terminate the server.
    Waits until app.state.ready is set if present (best-effort).
    """
    if port is None:
        port = pick_free_port(host)
    cfg = Config(app=app, host=host, port=port, log_level=log_level, loop="asyncio")
    server = Server(cfg)
    th = threading.Thread(target=server.run, name="uvicorn-server", daemon=True)
    th.start()
    started = time.time()
    # Wait until app startup has completed (ready Event set) or timeout
    while not getattr(app.state, "ready", None) or not app.state.ready.is_set():
        if time.time() - started > 10:
            raise RuntimeError("server failed to start within 10s")
        time.sleep(0.05)

    def _stop() -> None:
        server.should_exit = True
        th.join(timeout=10)

    return {"base_url": f"http://{host}:{port}", "stop": _stop}


# ------------------------------
# HTTP convenience for E2E flows
# ------------------------------


def api_create_agent(
    base_url: str,
    *,
    preset: str = "default",
    system: str | None = None,
) -> str:
    """Create an agent via HTTP POST /api/agents and return its id.

    Keeps E2E tests concise and consistent.
    """
    import requests

    body: dict[str, object] = {"preset": preset}
    if system is not None:
        body["system"] = system
    # Freeform metadata removed; preset is tracked internally only.
    resp = requests.post(f"{base_url}/api/agents", json=body)
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("id"))


# ------------------------------
# HTTP agent endpoint helpers
# ------------------------------


def agent_endpoint(agent_id: str, suffix: str | None = None) -> str:
    base = f"/api/agents/{agent_id}"
    return f"{base}/{suffix}" if suffix else base


def http_prompt(client, agent_id: str, text: str):
    return client.post(agent_endpoint(agent_id, "prompt"), json={"text": text})


def http_abort(client, agent_id: str):
    return client.post(agent_endpoint(agent_id, "abort"))


def http_snapshot(client, agent_id: str):
    return client.get(agent_endpoint(agent_id, "snapshot"))


def http_set_policy(client, agent_id: str, content: str, proposal_id: str | None = None):
    body: dict[str, object] = {"content": content}
    if proposal_id is not None:
        body["proposal_id"] = proposal_id
    return client.post(agent_endpoint(agent_id, "policy"), json=body)


# --------------------------------
# Payload assertion helper routines
# --------------------------------


def expect_error(
    payloads: Sequence[ServerMessage], *, code: ErrorCode | str, message_substr: str | None = None
) -> None:
    """Assert that an ErrorEvt with a given code (and optional message substring) is present.

    Uses PyHamcrest matchers against typed Pydantic models.
    """
    # Normalize string to enum for stable equality
    code_enum = ErrorCode(code) if isinstance(code, str) else code
    m = has_properties(type="error", code=code_enum)
    if message_substr:
        m = all_of(m, has_properties(message=contains_string(message_substr)))
    assert_that(payloads, has_item(m))


def expect_run_finished(payloads: Sequence[ServerMessage]) -> None:
    """Assert that a finished run_status is present in payloads (typed, hamcrest)."""
    assert_that(
        payloads,
        has_item(
            has_properties(type="run_status", run_state=has_properties(status=RunStatus.FINISHED))
        ),
    )
