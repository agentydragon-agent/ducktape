"""Fixtures for adgn tests not in agent_core.testing."""

from agent_core.testing import LIVE, make_mock
import pytest

__all__ = ["openai_client_param"]


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
