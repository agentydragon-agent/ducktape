from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectionFactorSources:
    home_value: dict[str, str]
    rent: dict[str, str]

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ProjectionFactorSources:
        raw = config.get("projection_factor_sources")
        if not isinstance(raw, dict):
            raise ValueError("joint config must define projection_factor_sources")
        return cls(home_value=_factor_sources(raw, "home_value"), rent=_factor_sources(raw, "rent"))

    def market_factor_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(("sp500", *self.home_value.values(), *self.rent.values(), "inflation")))


def _factor_sources(raw: dict[str, Any], key: str) -> dict[str, str]:
    value = raw.get(key)
    if not isinstance(value, dict) or not value:
        raise ValueError(f"projection_factor_sources.{key} must be a non-empty object")
    return {str(factor_id): str(source_factor) for factor_id, source_factor in value.items()}


def build_projection_factor_maps(
    *, path_by_factor: dict[str, list[float]], sources: ProjectionFactorSources
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    return (
        _build_factor_map(path_by_factor, sources.home_value, "home_value"),
        _build_factor_map(path_by_factor, sources.rent, "rent"),
    )


def _build_factor_map(
    path_by_factor: dict[str, list[float]], source_by_factor_id: dict[str, str], kind: str
) -> dict[str, list[float]]:
    mapped: dict[str, list[float]] = {}
    for factor_id, source_factor in source_by_factor_id.items():
        try:
            mapped[factor_id] = path_by_factor[source_factor]
        except KeyError as error:
            raise ValueError(
                f"projection_factor_sources.{kind}.{factor_id} references unknown source factor {source_factor!r}"
            ) from error
    return mapped
