from __future__ import annotations

from collections.abc import Awaitable, Callable
import os
from pathlib import Path
from typing import Any, cast

import openai
from openai import AsyncOpenAI
import pytest

from .support.openai_mock import LIVE, OpenAIClient, make_mock
from adgn.llm.mcp._shared.container_session import ContainerOptions
from adgn.llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.mcp_manager import McpManager


# Ensure MiniCodex logs go to a temp dir in tests
@pytest.fixture(autouse=True)
def _mini_codex_logdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "mini_codex_logs"
    monkeypatch.setenv("MINICODEX_LOG_DIR", str(log_dir))


## Adapter response builders and responses_factory are provided by tests.fixtures.responses


# --- Opt-in OpenAI client policy for tests ---
# By default, tests should NOT create real AsyncOpenAI() instances. Replace the
# constructor with a raising stub so tests must explicitly opt-in via the
# `openai_client` fixture when they need a real (or mocked) AsyncOpenAI instance.

_orig_async = getattr(openai, "AsyncOpenAI", None)


def _raising_async(*args, **kwargs):
    raise RuntimeError(
        "AsyncOpenAI() is disabled by default for tests.\n"
        "If a test needs an OpenAI client, request the `openai_client` fixture or add an explicit patch.\n"
        "This ensures tests explicitly opt-in to using live/mocked clients and avoid accidental network calls.",
    )


@pytest.fixture(autouse=True)
def fail_openai_by_default(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Autouse fixture that replaces openai.AsyncOpenAI with a raising stub.

    Tests that need access must explicitly use the `openai_client` fixture which
    temporarily restores the real AsyncOpenAI constructor for that test.

    Exemption: tests marked @pytest.mark.live_llm are allowed to construct
    AsyncOpenAI directly (they already guard on OPENAI_API_KEY).
    """
    if request.node.get_closest_marker("live_llm") is not None:
        return
    monkeypatch.setattr(openai, "AsyncOpenAI", _raising_async)


@pytest.fixture
async def openai_client(monkeypatch: pytest.MonkeyPatch):
    """Opt-in fixture: restore the real AsyncOpenAI for the duration of the test and yield an instance.

    Usage:
        async def test_x(openai_client):
            resp = await openai_client.responses.create(...)
    """
    if _orig_async is None:
        raise RuntimeError(
            "No openai.AsyncOpenAI available in this environment to restore",
        )

    # restore the original constructor for this test
    monkeypatch.setattr(openai, "AsyncOpenAI", _orig_async)
    client = _orig_async()
    try:
        yield client
    finally:
        # cleanup client if it supports aclose()
        try:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                await aclose()
        finally:
            # ensure we put back the raising stub
            monkeypatch.setattr(openai, "AsyncOpenAI", _raising_async)


# --- Minimal, function-shaped mock for responses.create ---
# Tests can parametrize a single async function shaped like client.responses.create
# and receive a client whose `responses.create(**kwargs)` forwards to that function.

ResponsesCreateFn = Callable[..., Awaitable[Any]]


@pytest.fixture
def responses_create_fn(
    request,
) -> ResponsesCreateFn:  # provided via indirect parametrize
    return cast(ResponsesCreateFn, request.param)


@pytest.fixture
def openai_client_mock(responses_create_fn: ResponsesCreateFn):
    class _Responses:
        async def create(self, **kwargs: Any) -> Any:  # mirror SDK surface
            return await responses_create_fn(**kwargs)

    class _Client:
        def __init__(self) -> None:
            self.responses = _Responses()

    return _Client()


# Live AsyncOpenAI for tests that opt into LIVE sentinel
@pytest.fixture(scope="session")
def live_openai() -> AsyncOpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    return AsyncOpenAI()


# --- Single-param OpenAI fixture (mock OR live via sentinel) ---
# Usage in tests:
#   @pytest.mark.parametrize(
#       "openai_client_param",
#       [pytest.param(behavior_fn, id="mock"), pytest.param("live", id="live", marks=pytest.mark.live_llm)],
#       indirect=True,
#   )
#   async def test_shared(openai_client_param):
#       ...


@pytest.fixture
def openai_client_param(
    request, live_openai
) -> OpenAIClient:  # provided via indirect parametrize
    val = request.param
    if callable(val):  # behavior function → mock
        return make_mock(val)
    if val is LIVE:
        return live_openai
    raise TypeError("openai_client_param must be a behavior fn or LIVE")


# ---- Shared ContainerOptions fixtures and in-proc docker exec specs ----
# Hoisted from mini_codex/conftest.py so MCP tests can reuse them.


@pytest.fixture
def container_opts_py312() -> ContainerOptions:
    return ContainerOptions(
        image="python:3.12-slim",
        working_dir="/workspace",
        volumes=None,
        describe=False,
    )


@pytest.fixture
def container_opts_alpine() -> ContainerOptions:
    return ContainerOptions(image="alpine:3.19", describe=False)


@pytest.fixture
def docker_exec_server_py312(container_opts_py312) -> object:
    return make_container_exec_mcp(container_opts_py312)


@pytest.fixture
def docker_exec_server_alpine(container_opts_alpine) -> object:
    return make_container_exec_mcp(container_opts_alpine)


@pytest.fixture
def docker_inproc_spec_py312(docker_exec_server_py312) -> object:
    return make_inproc_slot_spec(docker_exec_server_py312)


@pytest.fixture
def docker_inproc_spec_alpine(docker_exec_server_alpine) -> object:
    return make_inproc_slot_spec(docker_exec_server_alpine)


@pytest.fixture
def docker_specs_py312(docker_inproc_spec_py312) -> dict[str, object]:
    return {"docker": docker_inproc_spec_py312}


@pytest.fixture
async def empty_mcp() -> McpManager:
    """A real McpManager with zero servers, entered for the test duration."""
    mgr = McpManager({})
    await mgr.__aenter__()
    try:
        yield mgr
    finally:
        await mgr.__aexit__(None, None, None)
