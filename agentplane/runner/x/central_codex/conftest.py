from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentplane.native.codex.testing.responses import OpenAIResponses
from util.testing.undeclared_outputs import undeclared_outputs_dir


@pytest.fixture
async def model() -> AsyncIterator[OpenAIResponses]:
    async with OpenAIResponses() as endpoint:
        yield endpoint


@pytest.fixture
def logs(request: pytest.FixtureRequest) -> Path:
    root = undeclared_outputs_dir() / str(request.node.name)
    root.mkdir(parents=True)
    return root
