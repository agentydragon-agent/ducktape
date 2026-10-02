"""Native runner fixtures, with no integration app or app database."""

from collections.abc import AsyncIterator
from typing import cast

import pytest

from agentplane.runner.conftest import client, config, endpoint, harness, model, runner, spec, workspace
from agentplane.sandbox_service.egress import EgressInventory
from agentplane.sandbox_service.testing.fake_inventory import NAMESPACE, FakeCoreV1Api, FakeCustomObjectsApi
from agentplane.sandbox_service.testing.kubernetes import Cluster, kubernetes
from util.kubernetes import CustomObjectsClient


@pytest.fixture
async def cluster() -> AsyncIterator[Cluster]:
    async with kubernetes() as started:
        yield started


@pytest.fixture
def custom_objects() -> FakeCustomObjectsApi:
    return FakeCustomObjectsApi()


@pytest.fixture
def core_v1() -> FakeCoreV1Api:
    return FakeCoreV1Api()


@pytest.fixture
def egress(custom_objects: FakeCustomObjectsApi) -> EgressInventory:
    return EgressInventory(namespace=NAMESPACE, custom_objects=cast(CustomObjectsClient, custom_objects))
