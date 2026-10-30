"""Common suite clients use the running deployment without staging defaults."""

import pytest

from agentplane.system_tests.cluster import Cluster
from agentplane.system_tests.k3s.stack import Stack


@pytest.fixture(scope="session")
def base_url(deployment: Stack) -> str:
    return deployment.base_url


@pytest.fixture(scope="session")
def token(deployment: Stack) -> str:
    return deployment.token


@pytest.fixture(scope="session")
def cluster(deployment: Stack) -> Cluster:
    return deployment.cluster
