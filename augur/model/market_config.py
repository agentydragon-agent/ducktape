from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from augur.core.schemas import SourceDataConfig, StrictModel
from augur.model.location_market_sources import LocationMarketSourcesConfig


class MarketConfig(StrictModel):
    source_data: SourceDataConfig
    location_market_sources: LocationMarketSourcesConfig


def parse_market_config(payload: Any) -> MarketConfig:
    return MarketConfig.model_validate(payload)


def load_market_config(path: Path) -> MarketConfig:
    return parse_market_config(json.loads(path.read_text(encoding="utf-8")))
