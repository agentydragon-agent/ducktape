from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from augur.model.schemas import StrictModel


class LocationSeriesSourcesConfig(StrictModel):
    home_value: dict[str, str] = Field(min_length=1)
    rent: dict[str, str] = Field(min_length=1)


@dataclass(frozen=True)
class LocationSeriesSources:
    home_value: dict[str, str]
    rent: dict[str, str]

    @classmethod
    def from_config(cls, config: LocationSeriesSourcesConfig) -> LocationSeriesSources:
        return cls(home_value=dict(config.home_value), rent=dict(config.rent))
