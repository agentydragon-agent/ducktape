from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from augur.api.config import Config, load_augur_config
from augur.api.server import ApiServerConfig, create_app
from augur.product.testing import capacity_limited_private_equity_fixture, forced_private_equity_event_fixture
from util.bazel.runfiles import get_required_path


@pytest.fixture(scope="module")
def augur_config() -> Config:
    return load_augur_config(get_required_path("_main/augur/api/testdata/config.yaml"))


@pytest.fixture
def forced_private_equity_event_client(augur_config: Config) -> Iterator[TestClient]:
    with _client_with(augur_config, {"current_model": forced_private_equity_event_fixture()}) as client:
        yield client


@pytest.fixture
def capacity_limited_private_equity_client(augur_config: Config) -> Iterator[TestClient]:
    with _client_with(augur_config, {"current_model": capacity_limited_private_equity_fixture()}) as client:
        yield client


def _client_with(augur_config: Config, exogenous_models: dict[str, Any]) -> TestClient:
    return TestClient(
        create_app(ApiServerConfig(augur_config=augur_config, exogenous_models=exogenous_models, price_clients={}))
    )
