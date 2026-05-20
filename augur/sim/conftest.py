"""Pytest fixtures for simulator scenarios."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from augur.model.sim_market import MarketBundle
from augur.model.sim_market_deterministic import Deterministic

DeterministicMarketBundleFactory = Callable[[Sequence[float]], MarketBundle]


@pytest.fixture
def deterministic_market_bundle() -> DeterministicMarketBundleFactory:
    def build(levels: Sequence[float], *, asset_id: str = "vti") -> MarketBundle:
        return MarketBundle.independent({asset_id: Deterministic(levels=list(levels))})

    return build
