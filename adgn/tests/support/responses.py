"""Fixtures for adgn tests not in agent_core.testing."""

import pytest

from agent_core_testing.openai_mock import LIVE, make_mock


@pytest.fixture
def openai_client_param(request, live_openai):
    """Parametrized OpenAI client fixture for tests.

    Use with @pytest.mark.parametrize to switch between mock and live:
        @pytest.mark.parametrize("openai_client_param", [make_behavior, LIVE], indirect=True)
    """
    param = getattr(request, "param", None)
    if param is LIVE:
        return live_openai
    if callable(param):
        return make_mock(param)
    pytest.skip("openai_client_param requires a behavior function or LIVE sentinel")
