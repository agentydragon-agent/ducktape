from __future__ import annotations

from collections.abc import Sequence
import threading
import time
from typing import TYPE_CHECKING, Any

from hamcrest import all_of, assert_that, contains_string, has_item, has_properties, instance_of
import requests
from uvicorn import Config, Server

from adgn.agent.server.protocol import ErrorCode, RunStatus, ServerMessage
from adgn.openai_utils.model import (
    FunctionCallItem,
    FunctionCallOutputItem,
    OpenAIModelProto,
    ResponsesRequest,
    ResponsesResult,
)
from adgn.util.net import pick_free_port

if TYPE_CHECKING:
    from playwright.sync_api import Page

# System notification tag constants
SYSTEM_NOTIFICATION_START_TAG = "<system notification>"
SYSTEM_NOTIFICATION_END_TAG = "</system notification>"


class NoopOpenAIClient(OpenAIModelProto):
    """No-op OpenAI client for tests that bypass sampling via SyntheticAction."""

    async def responses_create(self, req: ResponsesRequest) -> ResponsesResult:
        # This should never be called when using SyntheticAction path
        raise NotImplementedError("NoopOpenAIClient should not be called in SyntheticAction path")


def strip_system_notification_wrapper(text: str) -> str:
    """Strip system notification wrapper tags if present, returning inner content."""
    start_tag = SYSTEM_NOTIFICATION_START_TAG + "\n"
    end_tag = "\n" + SYSTEM_NOTIFICATION_END_TAG
    if text.startswith(start_tag) and text.endswith(end_tag):
        return text[len(start_tag) : -len(end_tag)]
    return text


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


def api_create_agent(base_url: str, *, preset: str = "default", system: str | None = None) -> str:
    """Create an agent via HTTP POST /api/agents and return its id.

    Keeps E2E tests concise and consistent.
    """
    body: dict[str, object] = {"preset": preset}
    if system is not None:
        body["system"] = system
    # Freeform metadata removed; preset is tracked internally only.
    resp = requests.post(f"{base_url}/api/agents", json=body)
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("id"))


def e2e_open_agent_page(page: Any, base_url: str, agent_id: str, *, timeout: int = 10000) -> None:
    """Navigate to agent page and wait for WebSocket connection.

    Shared by all E2E tests to reduce duplication of the common
    page.goto + wait for WS connection pattern (appears 30+ times).

    Args:
        page: Playwright Page object
        base_url: Server base URL
        agent_id: Agent ID to connect to
        timeout: Timeout in milliseconds for WS connection (default 10s)
    """
    page.goto(f"{base_url}/?agent_id={agent_id}")
    page.locator(".ws .dot.on").wait_for(timeout=timeout)


def wait_for_pending_approvals(page: Page, count: int | None = None, timeout: int = 10000, **kwargs: Any) -> None:
    """Wait for Pending Approvals indicator to appear or disappear.

    Shared by all E2E tests to reduce duplication of the common
    wait for approval notification pattern (appears 19+ times).

    Args:
        page: Playwright page object
        count: Expected number of pending approvals (if known)
        timeout: Timeout in milliseconds (default 10s)
        **kwargs: Additional arguments to pass to wait_for (e.g., state="detached")
    """
    text = f"Pending Approvals ({count})" if count is not None else "Pending Approvals"
    page.get_by_text(text).wait_for(timeout=timeout, **kwargs)


def approve_first_pending(page: Page) -> None:
    """Click Approve button for first pending approval.

    Common E2E pattern for approving tool calls during agent execution.
    """
    page.get_by_role("button", name="Approve").first.click()


def send_prompt(page: Page, text: str) -> None:
    """Fill prompt textarea and click Send button.

    Common E2E pattern for submitting prompts to agent UI.
    Reduces duplication across ~26 E2E test cases.

    Args:
        page: Playwright page object
        text: Prompt text to send
    """
    page.locator('textarea[placeholder^="Type a prompt"]').fill(text)
    page.get_by_role("button", name="Send").click()


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


def _message_contains(fragment: str):
    """Return a matcher ensuring an error message contains ``fragment``."""

    return has_properties(message=contains_string(fragment))


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
        m = all_of(m, _message_contains(message_substr))
    assert_that(payloads, has_item(m))


def expect_run_finished(payloads: Sequence[ServerMessage]) -> None:
    """Assert that a finished run_status is present in payloads (typed, hamcrest)."""
    assert_that(
        payloads, has_item(has_properties(type="run_status", run_state=has_properties(status=RunStatus.FINISHED)))
    )


# --------------------------------
# E2E MCP server attachment helpers
# --------------------------------


def attach_echo_mcp(base_url: str, agent_id: str) -> None:
    """Attach echo MCP server to agent for testing.

    Common E2E setup pattern for MCP integration tests.
    Uses the simple echo server from testing utilities.
    """
    spec = {
        "echo": {
            "transport": "inproc",
            "factory": "adgn.mcp.testing.simple_servers:make_simple_mcp"
        }
    }
    patch = requests.patch(base_url + f"/api/agents/{agent_id}/mcp", json={"attach": spec})
    assert patch.ok, patch.text


# --------------------------------
# OpenAI model item matcher factories
# --------------------------------


def is_function_call_item(**props):
    """Matcher: FunctionCallItem with optional property constraints.

    Composable matcher factory for FunctionCallItem with type checking.
    Example: is_function_call_item(call_id="call_1", id="fc_id_1")
    """
    m = [instance_of(FunctionCallItem)]
    if props:
        m.append(has_properties(**props))
    return all_of(*m)


def is_function_call_output_item(**props):
    """Matcher: FunctionCallOutputItem with optional property constraints.

    Composable matcher factory for FunctionCallOutputItem with type checking.
    Example: is_function_call_output_item(call_id="call_1")
    """
    m = [instance_of(FunctionCallOutputItem)]
    if props:
        m.append(has_properties(**props))
    return all_of(*m)
