from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

    def market_factor_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(("sp500", *self.home_value.values(), *self.rent.values(), "inflation")))


def build_location_market_maps(
    *, path_by_factor: dict[str, Any], sources: LocationMarketSources
) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        _build_factor_map(path_by_factor, sources.home_value, "home_value"),
        _build_factor_map(path_by_factor, sources.rent, "rent"),
    )


def _build_factor_map(
    path_by_factor: dict[str, Any], source_by_location_id: dict[str, str], kind: str
) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for location_id, source_factor in source_by_location_id.items():
        try:
            mapped[location_id] = path_by_factor[source_factor]
        except KeyError as error:
            raise ValueError(
                f"location_market_sources.{kind}.{location_id} references unknown source factor {source_factor!r}"
            ) from error
    return mapped
