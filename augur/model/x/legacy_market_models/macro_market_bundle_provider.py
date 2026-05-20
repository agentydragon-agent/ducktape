"""Generic macro market-bundle provider.

Wraps any pre-fit `MarketModel` implementation from `augur.model.markets.models.*`
as a `MarketBundleProvider`. Model fit/training happens offline and is loaded
from a per-model trained-state blob at deployment time — see
`augur.model.market_provider_config` for the discriminated config union that
owns the model-specific load logic.

This class is purely the assembly layer: take the model's per-factor
multiplier paths, map them to per-location home/rent paths via
`location_market_sources`, fill in placeholder PE / crypto paths, and build
the `MarketBundle`. Private-equity sale opportunities, mortgage rates, and
location-specific path selection are runtime bundle concerns; the macro
model only owns the joint factor process.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from augur.core.market_bundle import MarketBundle, MarketBundleMetadata, RequiredMarketKeys
from augur.core.provenance import stable_identity_digest
from augur.core.scenario_set import MarketRequest
from augur.model.location_market_sources import LocationMarketSources, build_location_market_maps
from augur.model.train.market_model import MarketModel

_TENDER_INTERVAL_MONTHS = 12
_MODEL_CARD_ID = "augur-market-model-card:2026-05-15"
_VALIDATION_REPORT_ID = "validation_report:augur-market-models:not_available:2026-05-15"
_KNOWN_LIMITATION_IDS = (
    "evidence-set-id-unversioned",
    "calibration-artifact-id-unversioned",
    "validation-report-not-decision-grade",
    "constant-mortgage-rate-path",
    "private-equity-marks-flat-fixture",
    # The macro provider produces a single flat PE / crypto multiplier and one
    # tender-mask path, replicated across every required issuer / symbol key.
    # A real per-issuer / per-symbol joint model is a future slice.
    "private-equity-paths-all-share-placeholder",
    "crypto-paths-all-share-placeholder",
)


@dataclass(frozen=True)
class MacroMarketBundleProvider:
    """A bundle provider backed by a pre-loaded macro market model.

    Historically constructed by each `MarketProviderConfig` subclass's `realize(...)` —
    the config carries the trained-state blob path, the deployment-side
    market-state snapshot (`latest_observations`, current mortgage rate),
    and the per-location factor mapping; `realize` loads the model and
    feeds those bits into this class verbatim.
    """

    model: MarketModel
    latest_observations: dict[str, Any]
    current_mortgage30_rate_pct: float
    current_private_equity_price_usd: float
    location_market_sources: LocationMarketSources
    label: str
    factor_index: dict[str, int]
    risk_factor_ids: tuple[str, ...]
    evidence_latest_observation_ids: tuple[str, ...]
    risk_factor_set_id: str
    market_model_version_id: str
    evidence_set_id: str
    calibration_artifact_id: str

    @classmethod
    def from_loaded_model(
        cls,
        model: MarketModel,
        *,
        latest_observations: dict[str, Any],
        current_mortgage30_rate_pct: float,
        current_private_equity_price_usd: float,
        location_market_sources: LocationMarketSources,
        evidence_source_id: str,
    ) -> MacroMarketBundleProvider:
        """Compose a provider from a pre-fit `MarketModel` and the manifest
        fields that describe the calibration context. `evidence_source_id`
        is a stable string the manifest carries (e.g. its filename) so the
        evidence_set_id digest depends on the deployment's calibration
        manifest rather than re-derived data.
        """
        factor_names = tuple(model.factor_names)
        label = model.label
        risk_factor_set_id = "risk_factor_set:" + stable_identity_digest({"factor_names": factor_names})
        market_model_version_id = "model_version:" + stable_identity_digest(
            {"label": label, "class": type(model).__qualname__}
        )
        evidence_set_id = "evidence_set:" + stable_identity_digest(
            {
                "evidence_source_id": evidence_source_id,
                "factor_names": factor_names,
                "latest_observations": dict(latest_observations),
            }
        )
        calibration_artifact_id = "calibration_artifact:" + stable_identity_digest(
            {
                "market_model_id": label,
                "market_model_version_id": market_model_version_id,
                "evidence_set_id": evidence_set_id,
                "risk_factor_set_id": risk_factor_set_id,
            }
        )
        return cls(
            model=model,
            latest_observations=dict(latest_observations),
            current_mortgage30_rate_pct=float(current_mortgage30_rate_pct),
            current_private_equity_price_usd=float(current_private_equity_price_usd),
            location_market_sources=location_market_sources,
            label=label,
            factor_index={name: idx for idx, name in enumerate(factor_names)},
            risk_factor_ids=factor_names,
            evidence_latest_observation_ids=tuple(sorted(str(key) for key in latest_observations)),
            risk_factor_set_id=risk_factor_set_id,
            market_model_version_id=market_model_version_id,
            evidence_set_id=evidence_set_id,
            calibration_artifact_id=calibration_artifact_id,
        )

    def sample_market_bundle(
        self,
        *,
        rollout_count: int,
        horizon_months: int,
        seed: int,
        market_request: MarketRequest,
        required_keys: RequiredMarketKeys,
    ) -> MarketBundle:
        scenarios = self.model.simulate(n_paths=rollout_count, n_months=horizon_months, seed=seed)
        shape = (rollout_count, horizon_months + 1)
        path_by_factor: dict[str, np.ndarray] = {
            factor_name: scenarios.multipliers[:, :, factor_index]
            for factor_name, factor_index in self.factor_index.items()
        }
        home_value_paths_by_location, rent_paths_by_location = build_location_market_maps(
            path_by_factor=path_by_factor, sources=self.location_market_sources
        )
        # Strict required-keys contract: bundle carries exactly the keys the
        # scenario set declared. Empty dicts are legal when no scenario uses
        # that asset class (see `MarketBundle.__post_init__`).
        _require_location_paths("home_value", home_value_paths_by_location, required_keys.location_ids)
        _require_location_paths("rent", rent_paths_by_location, required_keys.location_ids)
        home_value_paths_by_location = {key: home_value_paths_by_location[key] for key in required_keys.location_ids}
        rent_paths_by_location = {key: rent_paths_by_location[key] for key in required_keys.location_ids}

        private_equity_events = np.zeros(shape, dtype=np.bool_)
        private_equity_events[:, _TENDER_INTERVAL_MONTHS : horizon_months + 1 : _TENDER_INTERVAL_MONTHS] = True
        private_equity_value_multipliers = np.ones(shape, dtype="float64")
        crypto_value_multipliers = np.ones(shape, dtype="float64")

        return MarketBundle(
            month_index=np.arange(horizon_months + 1, dtype="int64"),
            inflation_multipliers=path_by_factor["inflation"],
            generic_sp500_multipliers=path_by_factor["sp500"],
            home_value_multipliers_by_location=home_value_paths_by_location,
            rent_multipliers_by_location=rent_paths_by_location,
            mortgage_30y_rate_pct=np.full(shape, self.current_mortgage30_rate_pct, dtype="float64"),
            private_equity_value_multipliers_by_issuer=dict.fromkeys(
                required_keys.pe_issuer_ids, private_equity_value_multipliers
            ),
            private_equity_sale_opportunity_mask_by_issuer=dict.fromkeys(
                required_keys.pe_issuer_ids, private_equity_events
            ),
            crypto_value_multipliers_by_symbol=dict.fromkeys(required_keys.crypto_symbols, crypto_value_multipliers),
            metadata=MarketBundleMetadata(
                market_model_id=market_request.market_model_id,
                model_card_id=_MODEL_CARD_ID,
                model_version_id=self.market_model_version_id,
                validation_report_id=_VALIDATION_REPORT_ID,
                known_limitation_ids=_KNOWN_LIMITATION_IDS,
                market_model_version_id=self.market_model_version_id,
                scenario_generator_id="macro_market_bundle_provider",
                scenario_generator_version_id="macro_market_bundle_provider:v1",
                evidence_set_id=self.evidence_set_id,
                calibration_artifact_id=self.calibration_artifact_id,
                risk_factor_set_id=self.risk_factor_set_id,
                risk_factor_ids=self.risk_factor_ids,
                evidence_latest_observation_ids=self.evidence_latest_observation_ids,
                seed=seed,
                rollout_count=rollout_count,
                horizon_months=horizon_months,
                event_stream_ids=("private_equity_sale_opportunity_event",),
                notes=("sampled by MacroMarketBundleProvider",),
                current_private_equity_price_usd=self.current_private_equity_price_usd,
                source_metadata={
                    "market_provider_label": self.label,
                    "latest_observation_ids": list(self.evidence_latest_observation_ids),
                },
            ),
        )


def _require_location_paths(kind: str, paths: dict[str, Any], required: frozenset[str]) -> None:
    missing = sorted(required - paths.keys())
    if missing:
        available = sorted(paths)
        raise ValueError(
            f"macro market model does not carry {kind} paths for required location(s) "
            f"{missing}; available={available}. Either add them to `location_market_sources.{kind}` "
            "in the market-provider config and retrain, or remove the scenarios that reference these locations."
        )
