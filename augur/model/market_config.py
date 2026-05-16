from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field

from augur.core.schemas import SourceDataConfig, StrictModel
from augur.model.location_market_sources import LocationMarketSourcesConfig


class MarketSimulationConfig(StrictModel):
    rollout_samples: int = Field(gt=0)


class MarketRuntimeConfig(StrictModel):
    sampler: str


class MarketConfig(StrictModel):
    horizon_start: str
    horizon_years: int = Field(default=30, gt=0)
    source_data: SourceDataConfig
    location_market_sources: LocationMarketSourcesConfig
    seed: int = 0
    simulation: MarketSimulationConfig
    runtime: MarketRuntimeConfig


def parse_market_config(payload: Any) -> MarketConfig:
    return MarketConfig.model_validate(payload)


def load_market_config(path: Path) -> MarketConfig:
    return parse_market_config(json.loads(path.read_text(encoding="utf-8")))
