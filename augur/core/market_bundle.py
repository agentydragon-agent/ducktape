from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from augur.core.local_regulation import LocationId
from augur.core.scenario_set import MarketRequest


@dataclass(frozen=True)
class MarketBundleMetadata:
    market_model_id: str
    random_seed: int | None
    rollout_count: int
    horizon_months: int
    factor_ids: tuple[str, ...]
    event_stream_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "market_model_id": self.market_model_id,
            "random_seed": self.random_seed,
            "rollout_count": self.rollout_count,
            "horizon_months": self.horizon_months,
            "factor_ids": list(self.factor_ids),
            "event_stream_ids": list(self.event_stream_ids),
            "notes": list(self.notes),
            "source_metadata": self.source_metadata,
        }


@dataclass(frozen=True)
class MarketBundle:
    """Shared sampled market paths for a scenario set.

    Arrays are shaped `(rollout, month)`, where month includes the initial
    month 0. The simulator consumes these arrays directly; conversion to
    JSON-safe columnar payloads happens only at the report boundary.
    """

    month_index: np.ndarray
    inflation_multipliers: np.ndarray
    generic_sp500_multipliers: np.ndarray
    home_value_multipliers_by_location: dict[str, np.ndarray]
    rent_multipliers_by_location: dict[str, np.ndarray]
    mortgage_30y_rate_pct: np.ndarray
    private_equity_value_multipliers: np.ndarray
    private_equity_liquidity_event_mask: np.ndarray
    private_equity_tender_sale_fraction: np.ndarray
    metadata: MarketBundleMetadata

    def __post_init__(self) -> None:
        expected_shape = (self.rollout_count, self.horizon_months + 1)
        if self.month_index.shape != (self.horizon_months + 1,):
            raise ValueError(f"month_index must be shaped ({self.horizon_months + 1},), got {self.month_index.shape}")
        if not np.array_equal(self.month_index, np.arange(self.horizon_months + 1, dtype="int64")):
            raise ValueError("month_index must be contiguous months starting at 0")

        self._validate_multiplier(
            self.inflation_multipliers, name="inflation_multipliers", expected_shape=expected_shape
        )
        self._validate_multiplier(
            self.generic_sp500_multipliers, name="generic_sp500_multipliers", expected_shape=expected_shape
        )
        self._validate_multiplier(
            self.private_equity_value_multipliers,
            name="private_equity_value_multipliers",
            expected_shape=expected_shape,
        )
        self._validate_float_matrix(
            self.mortgage_30y_rate_pct, name="mortgage_30y_rate_pct", expected_shape=expected_shape
        )
        self._validate_bool_matrix(
            self.private_equity_liquidity_event_mask,
            name="private_equity_liquidity_event_mask",
            expected_shape=expected_shape,
        )
        self._validate_fraction(
            self.private_equity_tender_sale_fraction,
            name="private_equity_tender_sale_fraction",
            expected_shape=expected_shape,
        )
        if np.any((self.private_equity_tender_sale_fraction > 0) & ~self.private_equity_liquidity_event_mask):
            raise ValueError("private_equity_tender_sale_fraction may be positive only during liquidity events")

        for name, values in self.home_value_multipliers_by_location.items():
            self._validate_multiplier(
                values, name=f"home_value_multipliers_by_location[{name!r}]", expected_shape=expected_shape
            )
        for name, values in self.rent_multipliers_by_location.items():
            self._validate_multiplier(
                values, name=f"rent_multipliers_by_location[{name!r}]", expected_shape=expected_shape
            )
        if "default" not in self.home_value_multipliers_by_location:
            raise ValueError("home_value_multipliers_by_location must include 'default'")
        if "default" not in self.rent_multipliers_by_location:
            raise ValueError("rent_multipliers_by_location must include 'default'")

    @property
    def rollout_count(self) -> int:
        return self.metadata.rollout_count

    @property
    def horizon_months(self) -> int:
        return self.metadata.horizon_months

    def home_value_multipliers(self, location_id: LocationId | str | None) -> np.ndarray:
        return self._location_path(self.home_value_multipliers_by_location, location_id, label="home value")

    def rent_multipliers(self, location_id: LocationId | str | None) -> np.ndarray:
        return self._location_path(self.rent_multipliers_by_location, location_id, label="rent")

    def _location_path(
        self, paths: dict[str, np.ndarray], location_id: LocationId | str | None, *, label: str
    ) -> np.ndarray:
        if location_id is None:
            key = "default"
        elif isinstance(location_id, LocationId):
            key = location_id.value
        else:
            key = str(location_id)
        try:
            return paths[key]
        except KeyError as error:
            available = sorted(paths)
            raise ValueError(f"missing {label} market path for location {key!r}; available={available}") from error

    @staticmethod
    def _validate_float_matrix(values: np.ndarray, *, name: str, expected_shape: tuple[int, int]) -> None:
        if not isinstance(values, np.ndarray):
            raise TypeError(f"{name} must be a numpy ndarray")
        if values.shape != expected_shape:
            raise ValueError(f"{name} must be shaped {expected_shape}, got {values.shape}")
        if not np.issubdtype(values.dtype, np.number):
            raise TypeError(f"{name} must have a numeric dtype")
        if not np.all(np.isfinite(values)):
            raise ValueError(f"{name} contains non-finite values")

    @classmethod
    def _validate_multiplier(cls, values: np.ndarray, *, name: str, expected_shape: tuple[int, int]) -> None:
        cls._validate_float_matrix(values, name=name, expected_shape=expected_shape)
        if np.any(values <= 0):
            raise ValueError(f"{name} must be positive")
        if not np.allclose(values[:, 0], 1.0):
            raise ValueError(f"{name} must start at 1.0 in month 0")

    @staticmethod
    def _validate_bool_matrix(values: np.ndarray, *, name: str, expected_shape: tuple[int, int]) -> None:
        if not isinstance(values, np.ndarray):
            raise TypeError(f"{name} must be a numpy ndarray")
        if values.shape != expected_shape:
            raise ValueError(f"{name} must be shaped {expected_shape}, got {values.shape}")
        if values.dtype != np.bool_:
            raise TypeError(f"{name} must have bool dtype")

    @classmethod
    def _validate_fraction(cls, values: np.ndarray, *, name: str, expected_shape: tuple[int, int]) -> None:
        cls._validate_float_matrix(values, name=name, expected_shape=expected_shape)
        if np.any((values < 0) | (values > 1)):
            raise ValueError(f"{name} must be in [0, 1]")


class MarketBundleProvider(Protocol):
    def sample_market_bundle(
        self, *, rollout_count: int, horizon_months: int, seed: int | None, market_request: MarketRequest
    ) -> MarketBundle: ...


def sample_market_bundle_for_request(provider: MarketBundleProvider, market_request: MarketRequest) -> MarketBundle:
    return provider.sample_market_bundle(
        rollout_count=int(market_request.rollout_count),
        horizon_months=int(market_request.horizon_months),
        seed=market_request.random_seed,
        market_request=market_request,
    )


class SimpleMarketBundleProvider:
    """Small stochastic provider used until richer market models plug in."""

    def sample_market_bundle(
        self, *, rollout_count: int, horizon_months: int, seed: int | None, market_request: MarketRequest
    ) -> MarketBundle:
        rng = np.random.default_rng(seed)
        month_index = np.arange(horizon_months + 1, dtype="int64")
        inflation = _lognormal_multiplier_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=3.0,
            annual_volatility_pct=1.5,
        )
        sp500 = _lognormal_multiplier_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=7.0,
            annual_volatility_pct=16.0,
        )
        private_equity_value = _lognormal_multiplier_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=8.0,
            annual_volatility_pct=35.0,
        )
        home_base = _lognormal_multiplier_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=3.5,
            annual_volatility_pct=8.0,
        )
        rent_base = _lognormal_multiplier_paths(
            rng,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            annual_return_pct=3.0,
            annual_volatility_pct=3.0,
        )
        mortgage_rate = _mortgage_rate_paths(
            rng, rollout_count=rollout_count, horizon_months=horizon_months, base_rate_pct=6.5
        )
        private_equity_events = np.zeros((rollout_count, horizon_months + 1), dtype=np.bool_)
        if horizon_months >= 12:
            event_draws = rng.random((rollout_count, horizon_months))
            private_equity_events[:, 1:] = event_draws < (1 / 72)
        tender_sale_fraction = np.where(private_equity_events, 1.0, 0.0).astype("float64")

        home_by_location = _location_factor_map(
            home_base,
            annual_adjustment_pct={
                LocationId.SAN_FRANCISCO_CA.value: 0.3,
                LocationId.VALLEJO_CA.value: -0.2,
                LocationId.MARE_ISLAND_VALLEJO_CA.value: -0.1,
            },
        )
        rent_by_location = _location_factor_map(
            rent_base,
            annual_adjustment_pct={
                LocationId.SAN_FRANCISCO_CA.value: 0.4,
                LocationId.VALLEJO_CA.value: -0.1,
                LocationId.MARE_ISLAND_VALLEJO_CA.value: 0.0,
            },
        )
        factor_ids = (
            "inflation",
            "generic_sp500",
            "private_equity_value",
            "mortgage_30y_rate",
            "home_value:default",
            "rent:default",
            *(f"home_value:{location.value}" for location in LocationId),
            *(f"rent:{location.value}" for location in LocationId),
        )
        metadata = MarketBundleMetadata(
            market_model_id=market_request.market_model_id,
            random_seed=seed,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            factor_ids=factor_ids,
            event_stream_ids=("private_equity_liquidity_event",),
            notes=("simple core stochastic provider; replaceable via MarketBundleProvider",),
        )
        return MarketBundle(
            month_index=month_index,
            inflation_multipliers=inflation,
            generic_sp500_multipliers=sp500,
            home_value_multipliers_by_location=home_by_location,
            rent_multipliers_by_location=rent_by_location,
            mortgage_30y_rate_pct=mortgage_rate,
            private_equity_value_multipliers=private_equity_value,
            private_equity_liquidity_event_mask=private_equity_events,
            private_equity_tender_sale_fraction=tender_sale_fraction,
            metadata=metadata,
        )


def _lognormal_multiplier_paths(
    rng: np.random.Generator,
    *,
    rollout_count: int,
    horizon_months: int,
    annual_return_pct: float,
    annual_volatility_pct: float,
) -> np.ndarray:
    monthly_sigma = annual_volatility_pct / 100 / np.sqrt(12)
    monthly_mu = annual_return_pct / 100 / 12 - 0.5 * monthly_sigma**2
    log_returns = rng.normal(monthly_mu, monthly_sigma, size=(rollout_count, horizon_months))
    paths = np.ones((rollout_count, horizon_months + 1), dtype="float64")
    if horizon_months > 0:
        paths[:, 1:] = np.exp(np.cumsum(log_returns, axis=1))
    return paths


def _mortgage_rate_paths(
    rng: np.random.Generator, *, rollout_count: int, horizon_months: int, base_rate_pct: float
) -> np.ndarray:
    monthly_shocks = rng.normal(0.0, 0.08, size=(rollout_count, horizon_months))
    paths = np.full((rollout_count, horizon_months + 1), base_rate_pct, dtype="float64")
    if horizon_months > 0:
        paths[:, 1:] = np.clip(base_rate_pct + np.cumsum(monthly_shocks, axis=1), 0.5, 15.0)
    return paths


def _location_factor_map(base: np.ndarray, *, annual_adjustment_pct: dict[str, float]) -> dict[str, np.ndarray]:
    horizon_months = base.shape[1] - 1
    months = np.arange(horizon_months + 1, dtype="float64")
    paths = {"default": base}
    for location, adjustment_pct in annual_adjustment_pct.items():
        adjustment = (1 + adjustment_pct / 100) ** (months / 12)
        paths[location] = base * adjustment[None, :]
    return paths
