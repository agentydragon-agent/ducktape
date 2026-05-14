from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np

from augur.core.local_regulation import LocationId
from augur.core.market_bundle import MarketBundle, MarketBundleMetadata
from augur.core.rollout_provider import RolloutProvider
from augur.core.scenario_set import MarketRequest
from augur.core.schemas import JointRolloutPath

_HOME_FACTOR_LOCATION_KEYS: dict[str, tuple[str, ...]] = {
    "sf_home": (LocationId.SAN_FRANCISCO_CA.value,),
    "vallejo_home": (LocationId.VALLEJO_CA.value, LocationId.MARE_ISLAND_VALLEJO_CA.value),
}

_RENT_FACTOR_LOCATION_KEYS: dict[str, tuple[str, ...]] = {
    "sf_rent": (LocationId.SAN_FRANCISCO_CA.value,),
    "vallejo_rent": (LocationId.VALLEJO_CA.value, LocationId.MARE_ISLAND_VALLEJO_CA.value),
}


class RolloutProviderMarketBundleProvider:
    """Adapt existing JointRolloutPath providers into the core MarketBundle API."""

    def __init__(self, rollout_provider: RolloutProvider) -> None:
        self.rollout_provider = rollout_provider

    def sample_market_bundle(
        self, *, rollout_count: int, horizon_months: int, seed: int | None, market_request: MarketRequest
    ) -> MarketBundle:
        effective_seed = self._effective_seed(seed)
        raw_rollouts = self.rollout_provider.sample_rollouts(n_rollouts=rollout_count, seed=effective_seed)
        if len(raw_rollouts) != rollout_count:
            raise ValueError(
                f"rollout provider returned {len(raw_rollouts)} rollouts for requested rollout_count={rollout_count}"
            )
        rollouts = tuple(JointRolloutPath.model_validate(rollout) for rollout in raw_rollouts)
        expected_months = horizon_months + 1
        month_index = np.arange(expected_months, dtype="int64")

        home_by_location = _factor_paths_by_location(
            rollouts=rollouts,
            base_field="home_value_multipliers",
            factor_map_field="home_value_factor_multipliers",
            factor_location_keys=_HOME_FACTOR_LOCATION_KEYS,
            horizon_months=horizon_months,
        )
        rent_by_location = _factor_paths_by_location(
            rollouts=rollouts,
            base_field="rent_multipliers",
            factor_map_field="rent_factor_multipliers",
            factor_location_keys=_RENT_FACTOR_LOCATION_KEYS,
            horizon_months=horizon_months,
        )
        private_equity_events = _private_equity_liquidity_arrays(rollouts, horizon_months=horizon_months)
        metadata = MarketBundleMetadata(
            market_model_id=market_request.market_model_id,
            random_seed=effective_seed,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            factor_ids=_factor_ids(rollouts),
            event_stream_ids=("private_equity_liquidity_event",),
            notes=("adapted from existing RolloutProvider.sample_rollouts JointRolloutPath output",),
            source_metadata=_source_metadata(self.rollout_provider),
        )
        return MarketBundle(
            month_index=month_index,
            inflation_multipliers=_stack_rollout_series(
                rollouts, "expense_inflation_multipliers", horizon_months=horizon_months
            ),
            generic_sp500_multipliers=_stack_rollout_series(
                rollouts, "portfolio_multipliers", horizon_months=horizon_months
            ),
            home_value_multipliers_by_location=home_by_location,
            rent_multipliers_by_location=rent_by_location,
            mortgage_30y_rate_pct=_stack_rollout_series(
                rollouts, "mortgage30_rate_path", horizon_months=horizon_months, require_positive_start=False
            ),
            private_equity_value_multipliers=_private_equity_value_multipliers(rollouts, horizon_months=horizon_months),
            private_equity_liquidity_event_mask=private_equity_events,
            metadata=metadata,
        )

    def _effective_seed(self, seed: int | None) -> int:
        if seed is not None:
            return seed
        return int(getattr(self.rollout_provider, "random_seed", 0))


def _stack_rollout_series(
    rollouts: tuple[JointRolloutPath, ...], field_name: str, *, horizon_months: int, require_positive_start: bool = True
) -> np.ndarray:
    rows = []
    expected_months = horizon_months + 1
    for rollout_index, rollout in enumerate(rollouts):
        values = np.asarray(getattr(rollout, field_name), dtype="float64")
        if values.shape[0] < expected_months:
            raise ValueError(f"rollouts[{rollout_index}].{field_name} length {values.shape[0]} < {expected_months}")
        values = values[:expected_months]
        if not np.all(np.isfinite(values)):
            raise ValueError(f"rollouts[{rollout_index}].{field_name} contains non-finite values")
        if np.any(values <= 0):
            raise ValueError(f"rollouts[{rollout_index}].{field_name} must be positive")
        if require_positive_start and not math.isclose(float(values[0]), 1.0):
            raise ValueError(f"rollouts[{rollout_index}].{field_name} must start at 1.0")
        rows.append(values)
    return np.vstack(rows).astype("float64", copy=False)


def _stack_factor_series(
    rollouts: tuple[JointRolloutPath, ...], factor_map_field: str, factor_id: str, *, horizon_months: int
) -> np.ndarray:
    rows = []
    expected_months = horizon_months + 1
    for rollout_index, rollout in enumerate(rollouts):
        factor_map = getattr(rollout, factor_map_field)
        try:
            raw_values = factor_map[factor_id]
        except KeyError as error:
            raise ValueError(f"rollouts[{rollout_index}].{factor_map_field} is missing {factor_id!r}") from error
        values = np.asarray(raw_values, dtype="float64")
        if values.shape[0] < expected_months:
            raise ValueError(
                f"rollouts[{rollout_index}].{factor_map_field}[{factor_id!r}] "
                f"length {values.shape[0]} < {expected_months}"
            )
        values = values[:expected_months]
        if not np.all(np.isfinite(values)):
            raise ValueError(f"rollouts[{rollout_index}].{factor_map_field}[{factor_id!r}] contains non-finite values")
        if np.any(values <= 0):
            raise ValueError(f"rollouts[{rollout_index}].{factor_map_field}[{factor_id!r}] must be positive")
        if not math.isclose(float(values[0]), 1.0):
            raise ValueError(f"rollouts[{rollout_index}].{factor_map_field}[{factor_id!r}] must start at 1.0")
        rows.append(values)
    return np.vstack(rows).astype("float64", copy=False)


def _factor_paths_by_location(
    *,
    rollouts: tuple[JointRolloutPath, ...],
    base_field: str,
    factor_map_field: str,
    factor_location_keys: dict[str, tuple[str, ...]],
    horizon_months: int,
) -> dict[str, np.ndarray]:
    paths = {"default": _stack_rollout_series(rollouts, base_field, horizon_months=horizon_months)}
    factor_ids = _ordered_factor_ids(getattr(rollouts[0], factor_map_field).keys())
    for factor_id in factor_ids:
        values = _stack_factor_series(rollouts, factor_map_field, factor_id, horizon_months=horizon_months)
        paths[factor_id] = values
        for location_key in factor_location_keys.get(factor_id, ()):
            paths[location_key] = values
    return paths


def _private_equity_value_multipliers(rollouts: tuple[JointRolloutPath, ...], *, horizon_months: int) -> np.ndarray:
    rows = []
    expected_months = horizon_months + 1
    for rollout_index, rollout in enumerate(rollouts):
        path = rollout.private_equity_path
        values = np.asarray(path.price_path, dtype="float64")
        if values.shape[0] < expected_months:
            raise ValueError(
                f"rollouts[{rollout_index}].private_equity_path.price_path length {values.shape[0]} < {expected_months}"
            )
        values = values[:expected_months]
        if not np.all(np.isfinite(values)) or np.any(values <= 0):
            raise ValueError(f"rollouts[{rollout_index}].private_equity_path.price_path must be positive finite")
        base_price = float(values[0])
        rows.append(values / base_price)
    return np.vstack(rows).astype("float64", copy=False)


def _private_equity_liquidity_arrays(rollouts: tuple[JointRolloutPath, ...], *, horizon_months: int) -> np.ndarray:
    shape = (len(rollouts), horizon_months + 1)
    event_mask = np.zeros(shape, dtype=np.bool_)
    for rollout_index, rollout in enumerate(rollouts):
        for event in rollout.private_equity_path.events:
            if event.month_index < 0 or event.month_index > horizon_months:
                continue
            event_mask[rollout_index, event.month_index] = True
    return event_mask


def _factor_ids(rollouts: tuple[JointRolloutPath, ...]) -> tuple[str, ...]:
    first = rollouts[0]
    values = [
        "inflation",
        "expense_inflation",
        "generic_sp500",
        "mortgage30_rate",
        "private_equity_value",
        "home_value:default",
        "rent:default",
    ]
    for factor_id in _ordered_factor_ids(first.home_value_factor_multipliers.keys()):
        values.append(f"home_value:{factor_id}")
        values.extend(f"home_value:{location_key}" for location_key in _HOME_FACTOR_LOCATION_KEYS.get(factor_id, ()))
    for factor_id in _ordered_factor_ids(first.rent_factor_multipliers.keys()):
        values.append(f"rent:{factor_id}")
        values.extend(f"rent:{location_key}" for location_key in _RENT_FACTOR_LOCATION_KEYS.get(factor_id, ()))
    return tuple(dict.fromkeys(values))


def _ordered_factor_ids(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(str(value) for value in values))


def _source_metadata(provider: RolloutProvider) -> dict[str, Any]:
    latest_observations = getattr(provider, "latest_observations", {})
    return {
        "rollout_provider_label": getattr(provider, "label", provider.__class__.__name__),
        "rollout_provider_horizon_start": getattr(provider, "horizon_start", None),
        "rollout_provider_horizon_months": getattr(provider, "horizon_months", None),
        "rollout_provider_random_seed": getattr(provider, "random_seed", None),
        "latest_observation_ids": sorted(str(key) for key in latest_observations),
    }
