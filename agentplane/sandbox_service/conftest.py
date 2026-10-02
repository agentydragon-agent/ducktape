"""Native runner fixtures, with no integration app or app database."""

from collections.abc import AsyncIterator

import pytest

from agentplane.runner.conftest import client, config, endpoint, harness, model, runner, spec, workspace
from agentplane.sandbox_service.testing.kubernetes import Cluster, kubernetes


@pytest.fixture
async def cluster() -> AsyncIterator[Cluster]:
    async with kubernetes() as started:
        yield started
