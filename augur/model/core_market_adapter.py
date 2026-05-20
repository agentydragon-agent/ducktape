"""Adapters from sim-native sampled market bundles to legacy core bundles."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from augur.core.market_bundle import (
    CORE_MARKET_RISK_FACTOR_IDS,
    MarketBundle as CoreMarketBundle,
    MarketBundleMetadata,
    RequiredMarketKeys,
)
from augur.core.scenario_set import MarketRequest
from augur.model.sim_market_api import JointMarketModel, MarketSamplingRequest, SampledMarketBundle
from augur.model.sim_market_series import (
    INFLATION_SERIES_ID,
    SP500_SERIES_ID,
    crypto_series_id,
    home_value_series_id,
    private_equity_sale_event_id,
    private_equity_series_id,
    rent_series_id,
)


@dataclass(frozen=True)
class CoreMarketBundleProviderShim:
    """Expose a sim-native joint market model through the legacy core provider API."""

    model: JointMarketModel
    current_private_equity_price_usd: float = 0.0
    mortgage_30y_rate_pct: float = 6.5
    scenario_generator_id: str = "sim_market_bundle_provider_shim"
    scenario_generator_version_id: str = "sim_market_bundle_provider_shim:v1"
    evidence_set_id: str = "sim_market_bundle"
    calibration_artifact_id: str = "sim_market_bundle"
    notes: tuple[str, ...] = ("sampled by sim-native market model; adapted to core MarketBundle",)

    def sample_market_bundle(
        self,
        *,
        rollout_count: int,
        horizon_months: int,
        seed: int,
        market_request: MarketRequest,
        required_keys: RequiredMarketKeys,
    ) -> CoreMarketBundle:
        sampled = self.model.sample(
            MarketSamplingRequest(
                horizon_months=horizon_months,
                rollout_seeds=_rollout_seeds(seed=seed, rollout_count=rollout_count),
                required_level_series=_required_level_series(required_keys),
                required_event_series=_required_event_series(required_keys),
            )
        )
        shape = (rollout_count, horizon_months + 1)
        metadata = MarketBundleMetadata(
            market_model_id=market_request.market_model_id,
            model_card_id=_optional_str_metadata(sampled, "model_card_id"),
            model_version_id=_optional_str_metadata(sampled, "model_version_id"),
            validation_report_id=_optional_str_metadata(sampled, "validation_report_id"),
            known_limitation_ids=_tuple_str_metadata(sampled, "known_limitation_ids"),
            market_model_version_id=_str_metadata(sampled, "market_model_version_id", "unknown"),
            scenario_generator_id=_str_metadata(sampled, "scenario_generator_id", self.scenario_generator_id),
            scenario_generator_version_id=_str_metadata(
                sampled, "scenario_generator_version_id", self.scenario_generator_version_id
            ),
            evidence_set_id=_str_metadata(sampled, "evidence_set_id", self.evidence_set_id),
            calibration_artifact_id=_str_metadata(sampled, "calibration_artifact_id", self.calibration_artifact_id),
            risk_factor_set_id=_str_metadata(sampled, "risk_factor_set_id", "core_market_factors:v1"),
            risk_factor_ids=_tuple_str_metadata(sampled, "risk_factor_ids", CORE_MARKET_RISK_FACTOR_IDS),
            evidence_latest_observation_ids=_tuple_str_metadata(sampled, "evidence_latest_observation_ids"),
            current_private_equity_price_usd=self.current_private_equity_price_usd,
            seed=seed,
            rollout_count=rollout_count,
            horizon_months=horizon_months,
            event_stream_ids=_tuple_str_metadata(
                sampled, "event_stream_ids", ("private_equity_sale_opportunity_event",)
            ),
            notes=_tuple_str_metadata(sampled, "notes", self.notes),
            source_metadata=dict(sampled.metadata),
        )
        return CoreMarketBundle(
            month_index=np.arange(horizon_months + 1, dtype="int64"),
            inflation_multipliers=_level_multiplier(
                sampled, INFLATION_SERIES_ID, rollout_count=rollout_count, horizon_months=horizon_months
            ),
            generic_sp500_multipliers=_level_multiplier(
                sampled, SP500_SERIES_ID, rollout_count=rollout_count, horizon_months=horizon_months
            ),
            home_value_multipliers_by_location={
                location_id: _level_multiplier(
                    sampled,
                    home_value_series_id(location_id),
                    rollout_count=rollout_count,
                    horizon_months=horizon_months,
                )
                for location_id in sorted(required_keys.location_ids)
            },
            rent_multipliers_by_location={
                location_id: _level_multiplier(
                    sampled, rent_series_id(location_id), rollout_count=rollout_count, horizon_months=horizon_months
                )
                for location_id in sorted(required_keys.location_ids)
            },
            mortgage_30y_rate_pct=np.full(shape, self.mortgage_30y_rate_pct, dtype="float64"),
            private_equity_value_multipliers_by_issuer={
                issuer_id: _level_multiplier(
                    sampled,
                    private_equity_series_id(issuer_id),
                    rollout_count=rollout_count,
                    horizon_months=horizon_months,
                )
                for issuer_id in sorted(required_keys.pe_issuer_ids)
            },
            private_equity_sale_opportunity_mask_by_issuer={
                issuer_id: sampled.event_matrix(
                    private_equity_sale_event_id(issuer_id), rollout_count=rollout_count, horizon_months=horizon_months
                )
                for issuer_id in sorted(required_keys.pe_issuer_ids)
            },
            crypto_value_multipliers_by_symbol={
                symbol: _level_multiplier(
                    sampled, crypto_series_id(symbol), rollout_count=rollout_count, horizon_months=horizon_months
                )
                for symbol in sorted(required_keys.crypto_symbols)
            },
            metadata=metadata,
        )


def _required_level_series(required_keys: RequiredMarketKeys) -> frozenset[str]:
    return frozenset(
        [
            INFLATION_SERIES_ID,
            SP500_SERIES_ID,
            *(home_value_series_id(location_id) for location_id in required_keys.location_ids),
            *(rent_series_id(location_id) for location_id in required_keys.location_ids),
            *(private_equity_series_id(issuer_id) for issuer_id in required_keys.pe_issuer_ids),
            *(crypto_series_id(symbol) for symbol in required_keys.crypto_symbols),
        ]
    )


def _required_event_series(required_keys: RequiredMarketKeys) -> frozenset[str]:
    return frozenset(private_equity_sale_event_id(issuer_id) for issuer_id in required_keys.pe_issuer_ids)


def _rollout_seeds(*, seed: int, rollout_count: int) -> tuple[int, ...]:
    return tuple(
        int(child.generate_state(1, dtype=np.uint64)[0]) for child in np.random.SeedSequence(seed).spawn(rollout_count)
    )


def _level_multiplier(
    sampled: SampledMarketBundle, series_id: str, *, rollout_count: int, horizon_months: int
) -> np.ndarray:
    levels = sampled.level_matrix(series_id, rollout_count=rollout_count, horizon_months=horizon_months)
    initial = levels[:, [0]]
    if np.any(initial <= 0):
        raise ValueError(f"sampled market level {series_id!r} must start positive to adapt to a core multiplier")
    return np.divide(levels, initial, out=np.ones_like(levels), where=initial > 0)


def _str_metadata(sampled: SampledMarketBundle, key: str, default: str) -> str:
    value = sampled.metadata.get(key, default)
    if not isinstance(value, str):
        raise TypeError(f"sampled market metadata {key!r} must be a string")
    return value


def _optional_str_metadata(sampled: SampledMarketBundle, key: str) -> str | None:
    value = sampled.metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"sampled market metadata {key!r} must be a string or None")
    return value


def _tuple_str_metadata(sampled: SampledMarketBundle, key: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = sampled.metadata.get(key, default)
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"sampled market metadata {key!r} must be a tuple[str, ...]")
    return value
