from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np
import polars as pl
from pydantic import Field, computed_field

from augur.core import event_streams
from augur.core.provenance import (
    CalibrationArtifact,
    CalibrationRun,
    EvidenceSet,
    ExogenousPathSet,
    KnownLimitation,
    ModelCard,
    ScenarioGeneratorRun,
    ValidationReport,
    calibration_run_id,
    exogenous_path_id,
    path_set_id,
    scenario_generator_run_id,
)
from augur.core.scenario_set import MarketRequest
from augur.core.schemas import ApiModel

CORE_MARKET_RISK_FACTOR_IDS = (
    "inflation",
    "sp500",
    "home",
    "rent",
    "mortgage_30y_rate_pct",
    "private_equity_value",
    "crypto_value",
)


class MarketBundleMetadata(ApiModel):
    market_model_id: str
    model_card_id: str | None = None
    model_version_id: str | None = None
    validation_report_id: str | None = None
    known_limitation_ids: tuple[str, ...] = ()
    market_model_version_id: str = "unknown"
    scenario_generator_id: str = "market_bundle_provider"
    scenario_generator_version_id: str = "unknown"
    evidence_set_id: str = "unknown"
    calibration_artifact_id: str = "unknown"
    risk_factor_set_id: str = "core_market_factors:v1"
    risk_factor_ids: tuple[str, ...] = ()
    evidence_latest_observation_ids: tuple[str, ...] = ()
    seed: int
    rollout_count: int
    horizon_months: int
    event_stream_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()
    current_private_equity_price_usd: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Per-unit USD mark for private equity at month 0. Used by the simulator to "
            "derive `PrivateEquityPosition.value_usd` from `units` when the position omits "
            "an explicit mark. Providers that drive PE valuation must set this; deterministic "
            "fixtures use 0.0 and require positions to supply `value_usd` directly."
        ),
    )
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def path_set_id(self) -> str:
        return path_set_id(
            market_model_id=self.market_model_id,
            market_model_version_id=self.market_model_version_id,
            scenario_generator_id=self.scenario_generator_id,
            scenario_generator_version_id=self.scenario_generator_version_id,
            evidence_set_id=self.evidence_set_id,
            calibration_artifact_id=self.calibration_artifact_id,
            risk_factor_set_id=self.risk_factor_set_id,
            seed=self.seed,
            rollout_count=self.rollout_count,
            horizon_months=self.horizon_months,
            event_stream_ids=self.event_stream_ids,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def model_card(self) -> ModelCard | None:
        if self.model_card_id is None:
            return None
        return ModelCard(model_card_id=self.model_card_id, model_version_id=self.model_version_id)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def validation_report(self) -> ValidationReport | None:
        if self.validation_report_id is None:
            return None
        return ValidationReport(
            validation_report_id=self.validation_report_id,
            model_version_id=self.model_version_id or self.market_model_version_id,
            evidence_set_id=self.evidence_set_id,
            calibration_artifact_id=self.calibration_artifact_id,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def known_limitations(self) -> tuple[KnownLimitation, ...]:
        return tuple(KnownLimitation(known_limitation_id=limitation_id) for limitation_id in self.known_limitation_ids)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_set(self) -> EvidenceSet:
        return EvidenceSet(
            evidence_set_id=self.evidence_set_id,
            risk_factor_set_id=self.risk_factor_set_id,
            factor_ids=self.risk_factor_ids,
            latest_observation_ids=self.evidence_latest_observation_ids,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def calibration_run(self) -> CalibrationRun:
        return CalibrationRun(
            calibration_run_id=calibration_run_id(
                model_version_id=self.market_model_version_id,
                evidence_set_id=self.evidence_set_id,
                risk_factor_set_id=self.risk_factor_set_id,
            ),
            model_version_id=self.market_model_version_id,
            evidence_set_id=self.evidence_set_id,
            risk_factor_set_id=self.risk_factor_set_id,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def calibration_artifact(self) -> CalibrationArtifact:
        return CalibrationArtifact(
            calibration_artifact_id=self.calibration_artifact_id,
            calibration_run_id=self.calibration_run.calibration_run_id,
            model_version_id=self.market_model_version_id,
            evidence_set_id=self.evidence_set_id,
            risk_factor_set_id=self.risk_factor_set_id,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scenario_generator_run(self) -> ScenarioGeneratorRun:
        return ScenarioGeneratorRun(
            scenario_generator_run_id=scenario_generator_run_id(
                market_model_id=self.market_model_id,
                model_version_id=self.market_model_version_id,
                scenario_generator_id=self.scenario_generator_id,
                scenario_generator_version_id=self.scenario_generator_version_id,
                evidence_set_id=self.evidence_set_id,
                calibration_artifact_id=self.calibration_artifact_id,
                risk_factor_set_id=self.risk_factor_set_id,
                seed=self.seed,
                rollout_count=self.rollout_count,
                horizon_months=self.horizon_months,
                event_stream_ids=self.event_stream_ids,
            ),
            scenario_generator_id=self.scenario_generator_id,
            scenario_generator_version_id=self.scenario_generator_version_id,
            market_model_id=self.market_model_id,
            model_version_id=self.market_model_version_id,
            evidence_set_id=self.evidence_set_id,
            calibration_artifact_id=self.calibration_artifact_id,
            risk_factor_set_id=self.risk_factor_set_id,
            seed=self.seed,
            rollout_count=self.rollout_count,
            horizon_months=self.horizon_months,
            event_stream_ids=self.event_stream_ids,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exogenous_path_set(self) -> ExogenousPathSet:
        return ExogenousPathSet(
            path_set_id=self.path_set_id,
            scenario_generator_run_id=self.scenario_generator_run.scenario_generator_run_id,
            rollout_count=self.rollout_count,
            horizon_months=self.horizon_months,
            event_stream_ids=self.event_stream_ids,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exogenous_path_ids(self) -> tuple[str, ...]:
        return tuple(
            exogenous_path_id(path_set_id=self.path_set_id, rollout_index=rollout_index)
            for rollout_index in range(self.rollout_count)
        )

    def to_json_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class MissingMarketFactorError(KeyError):
    """Raised when a scenario looks up a per-asset market factor the bundle does not carry.

    Scenarios declare which keys they need via `RequiredMarketKeys`; providers must
    populate every required key. Any miss is a contract violation between the
    scenario set and the market provider, not a "use a placeholder" condition.
    """

    def __init__(self, *, factor_name: str, key: str, available_keys: tuple[str, ...]) -> None:
        self.factor_name = factor_name
        self.key = key
        self.available_keys = available_keys
        super().__init__(
            f"missing {factor_name} market path for key {key!r}; available={list(available_keys)}. "
            "Scenarios must declare required keys up front (via RequiredMarketKeys) so the "
            "market provider can populate them; there is no fallback path."
        )


@dataclass(frozen=True)
class RequiredMarketKeys:
    """Per-scenario-set declaration of which keyed market paths the run needs.

    `simulate_set` extracts these from the scenario set and passes them to the
    `MarketBundleProvider.sample_market_bundle` call so the provider can populate
    exactly those keys (and raise if it cannot model one of them).
    """

    location_ids: frozenset[str] = frozenset()
    pe_issuer_ids: frozenset[str] = frozenset()
    crypto_symbols: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MarketBundle:
    """Shared sampled market paths for a scenario set.

    Arrays are shaped `(rollout, month)`, where month includes the initial
    month 0. The simulator consumes these arrays directly; conversion to
    JSON-safe columnar payloads happens only at the report boundary.

    All per-asset / per-location paths are keyed explicitly: scenarios declare
    which keys they need (via `RequiredMarketKeys`); the provider populates
    exactly those keys. There is no `"default"` fallback — looking up a missing
    key raises `MissingMarketFactorError`.
    """

    month_index: np.ndarray
    inflation_multipliers: np.ndarray
    generic_sp500_multipliers: np.ndarray
    home_value_multipliers_by_location: dict[str, np.ndarray]
    rent_multipliers_by_location: dict[str, np.ndarray]
    mortgage_30y_rate_pct: np.ndarray
    private_equity_value_multipliers_by_issuer: dict[str, np.ndarray]
    private_equity_sale_opportunity_mask_by_issuer: dict[str, np.ndarray]
    crypto_value_multipliers_by_symbol: dict[str, np.ndarray]
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
        self._validate_float_matrix(
            self.mortgage_30y_rate_pct, name="mortgage_30y_rate_pct", expected_shape=expected_shape
        )

        # Per-asset dicts are required to match `RequiredMarketKeys` declared by the
        # scenario set — including the legitimate "no scenarios use this asset class"
        # case, where the dict is empty. Mismatch is caught at lookup time via
        # `MissingMarketFactorError`, so no _require_nonempty baseline here.

        for name, values in self.home_value_multipliers_by_location.items():
            self._validate_multiplier(
                values, name=f"home_value_multipliers_by_location[{name!r}]", expected_shape=expected_shape
            )
        for name, values in self.rent_multipliers_by_location.items():
            self._validate_multiplier(
                values, name=f"rent_multipliers_by_location[{name!r}]", expected_shape=expected_shape
            )
        for name, values in self.private_equity_value_multipliers_by_issuer.items():
            self._validate_multiplier(
                values, name=f"private_equity_value_multipliers_by_issuer[{name!r}]", expected_shape=expected_shape
            )
        for name, values in self.private_equity_sale_opportunity_mask_by_issuer.items():
            self._validate_bool_matrix(
                values, name=f"private_equity_sale_opportunity_mask_by_issuer[{name!r}]", expected_shape=expected_shape
            )
        for name, values in self.crypto_value_multipliers_by_symbol.items():
            self._validate_multiplier(
                values, name=f"crypto_value_multipliers_by_symbol[{name!r}]", expected_shape=expected_shape
            )

    @property
    def rollout_count(self) -> int:
        return self.metadata.rollout_count

    @property
    def horizon_months(self) -> int:
        return self.metadata.horizon_months

    def home_value_multipliers(self, location_id: str) -> np.ndarray:
        return self._keyed_path(self.home_value_multipliers_by_location, location_id, factor_name="home_value")

    def rent_multipliers(self, location_id: str) -> np.ndarray:
        return self._keyed_path(self.rent_multipliers_by_location, location_id, factor_name="rent")

    def private_equity_value_multiplier(self, issuer_id: str) -> np.ndarray:
        return self._keyed_path(
            self.private_equity_value_multipliers_by_issuer, issuer_id, factor_name="private_equity_value"
        )

    def private_equity_sale_opportunity_mask_for(self, issuer_id: str) -> np.ndarray:
        return self._keyed_path(
            self.private_equity_sale_opportunity_mask_by_issuer,
            issuer_id,
            factor_name="private_equity_sale_opportunity_mask",
        )

    def crypto_value_multiplier(self, symbol: str) -> np.ndarray:
        return self._keyed_path(self.crypto_value_multipliers_by_symbol, symbol, factor_name="crypto_value")

    def market_path_observations_frame(self, *, location_id: str | None, pe_issuer_key: str | None) -> pl.DataFrame:
        """Build the dense `(rollouts × (months+1))` `MarketPathObservation`
        frame for one scenario's keys, with the legacy fallbacks: `None`
        location → all-ones home/rent multipliers; `None` issuer → all-ones
        PE multipliers + no sale-opportunity events.

        The engine used to assemble this on its own side; centralising the
        per-key lookups + fallbacks here keeps the bundle as the source of
        truth for what 'no scenario keys' means. Pure projection, no
        scenario-shaped logic — the engine still owns scenario→key
        translation (e.g. picking the first PE issuer for the path frame)."""

        shape = (self.rollout_count, self.horizon_months + 1)
        if location_id is None:
            home_multiplier = np.ones(shape, dtype="float64")
            rent_multiplier = np.ones(shape, dtype="float64")
        else:
            home_multiplier = self.home_value_multipliers(location_id)
            rent_multiplier = self.rent_multipliers(location_id)
        if pe_issuer_key is None:
            pe_value_multipliers = np.ones(shape, dtype="float64")
            pe_sale_mask = np.zeros(shape, dtype=np.bool_)
        else:
            pe_value_multipliers = self.private_equity_value_multiplier(pe_issuer_key)
            pe_sale_mask = self.private_equity_sale_opportunity_mask_for(pe_issuer_key)
        return event_streams.build_market_path_observations_frame(
            rollout_count=self.rollout_count,
            horizon_months=self.horizon_months,
            month_index=self.month_index,
            location_id=location_id,
            inflation_multipliers=self.inflation_multipliers,
            sp500_multipliers=self.generic_sp500_multipliers,
            pe_value_multipliers=pe_value_multipliers,
            home_value_multipliers=home_multiplier,
            rent_multipliers=rent_multiplier,
            mortgage_30y_rate_pct=self.mortgage_30y_rate_pct,
            pe_sale_opportunity_mask=pe_sale_mask,
        )

    @staticmethod
    def _keyed_path(paths: dict[str, np.ndarray], key: str, *, factor_name: str) -> np.ndarray:
        try:
            return paths[key]
        except KeyError as error:
            raise MissingMarketFactorError(
                factor_name=factor_name, key=key, available_keys=tuple(sorted(paths))
            ) from error

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


class MarketBundleProvider(Protocol):
    def sample_market_bundle(
        self,
        *,
        rollout_count: int,
        horizon_months: int,
        seed: int,
        market_request: MarketRequest,
        required_keys: RequiredMarketKeys,
    ) -> MarketBundle: ...


@runtime_checkable
class HorizonBoundMarketBundleProvider(MarketBundleProvider, Protocol):
    horizon_months: int


def sample_market_bundle_for_request(
    provider: MarketBundleProvider, market_request: MarketRequest, *, required_keys: RequiredMarketKeys
) -> MarketBundle:
    return provider.sample_market_bundle(
        rollout_count=int(market_request.rollout_count),
        horizon_months=int(market_request.horizon_months),
        seed=market_request.seed,
        market_request=market_request,
        required_keys=required_keys,
    )
