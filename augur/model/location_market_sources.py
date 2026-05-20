from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from augur.model.schemas import StrictModel


class LocationMarketSourcesConfig(StrictModel):
    home_value: dict[str, str] = Field(min_length=1)
    rent: dict[str, str] = Field(min_length=1)


@dataclass(frozen=True)
class LocationMarketSources:
    home_value: dict[str, str]
    rent: dict[str, str]

    @classmethod
    def from_config(cls, config: LocationMarketSourcesConfig) -> LocationMarketSources:
        return cls(home_value=dict(config.home_value), rent=dict(config.rent))
