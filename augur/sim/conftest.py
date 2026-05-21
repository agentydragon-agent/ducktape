"""Pytest fixtures for simulator scenarios."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from augur.model.deterministic import Deterministic
from augur.model.series_model import SeriesModelBundle

DeterministicSeriesModelBundleFactory = Callable[[Sequence[float]], SeriesModelBundle]


@pytest.fixture
def deterministic_series_bundle() -> DeterministicSeriesModelBundleFactory:
    def build(levels: Sequence[float], *, asset_id: str = "vti") -> SeriesModelBundle:
        return SeriesModelBundle.independent({asset_id: Deterministic(levels=list(levels))})

    return build
