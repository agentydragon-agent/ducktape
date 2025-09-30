from __future__ import annotations

from collections.abc import Awaitable, Callable
import os
from pathlib import Path
from typing import Any, cast

import openai
from openai import AsyncOpenAI
import pytest

from .support.openai_mock import LIVE, OpenAIClient, make_mock


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


# Docker/OpenAI fixtures moved to top-level tests/conftest.py to be shared across suites.
