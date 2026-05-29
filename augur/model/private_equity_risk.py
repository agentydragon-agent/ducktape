"""Prior-parameter private-equity realization-risk sampler."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import Field, model_validator

from augur.model.exogenous import (
    SERIES_LEVELS_SCHEMA,
    ExogenousSamplingRequest,
    SampledExogenousBundle,
    validate_sample_satisfies_request,
)
from augur.model.private_equity_bundle import PrivateEquityBundle
from augur.model.schemas import FrozenModel
from augur.model.series import PrivateEquityEventKindCode, PrivateEquityRegimeCode
from augur.model.series_model import derive_stream_rollout_seeds

BoolMatrix = npt.NDArray[np.bool_]
CodeMatrix = npt.NDArray[np.int64]
FloatMatrix = npt.NDArray[np.float64]


class PrivateEquityRiskIssuerConfig(FrozenModel):
    """Issuer-level prior parameters for the generic PE realization-risk sampler.

    The runtime artifact is intentionally just numbers. Distribution families live in
    sampler code so later fitting can update the same parameter vector without forcing
    config to carry provenance or distribution tags.
    """

    current_mark_usd: float = Field(gt=0)
    monthly_log_return_mu: float = 0.0
    monthly_log_return_sigma: float = Field(default=0.0, ge=0.0)
    student_t_nu: float = Field(default=5.0, gt=2.0)
    tender_interval_months_median: float = Field(default=12.0, gt=0.0)
    tender_interval_log_sigma: float = Field(default=0.5, ge=0.0)
    tender_price_log_discount_mu: float = 0.0
    tender_price_log_discount_sigma: float = Field(default=0.08, ge=0.0)
    tender_sale_capacity_alpha: float = Field(default=10.0, gt=0.0)
    tender_sale_capacity_beta: float = Field(default=1.0, gt=0.0)
    admin_mark_update_interval_months_median: float = Field(default=0.0, ge=0.0)
    admin_mark_update_interval_log_sigma: float = Field(default=0.5, ge=0.0)
    admin_mark_update_log_noise_mu: float = 0.0
    admin_mark_update_log_noise_sigma: float = Field(default=0.10, ge=0.0)
    eligible_fraction: float = Field(default=1.0, ge=0.0, le=1.0)
    annual_public_market_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    public_market_lockup_months: int = Field(default=0, ge=0)
    public_market_price_log_discount_mu: float = 0.0
    public_market_price_log_discount_sigma: float = Field(default=0.20, ge=0.0)
    annual_liquidity_suspension_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    liquidity_suspension_months_min: int = Field(default=1, ge=1)
    liquidity_suspension_months_max: int = Field(default=6, ge=1)
    annual_forced_sale_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    forced_sale_fraction_alpha: float = Field(default=1.0, gt=0.0)
    forced_sale_fraction_beta: float = Field(default=1.0, gt=0.0)
    annual_forced_recovery_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    forced_recovery_cashout_usd_min: float = Field(default=0.0, ge=0.0)
    forced_recovery_cashout_usd_max: float = Field(default=0.0, ge=0.0)
    annual_collapse_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    collapsed_mark_fraction: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_ranges(self) -> PrivateEquityRiskIssuerConfig:
        if self.liquidity_suspension_months_max < self.liquidity_suspension_months_min:
            raise ValueError("liquidity_suspension_months_max must be >= min")
        if self.forced_recovery_cashout_usd_max < self.forced_recovery_cashout_usd_min:
            raise ValueError("forced_recovery_cashout_usd_max must be >= min")
        return self


class PrivateEquityRiskProviderConfig(FrozenModel):
    type: Literal["private_equity_risk"] = "private_equity_risk"
    issuers: dict[str, PrivateEquityRiskIssuerConfig] = Field(min_length=1)

    def realize_model(self) -> PrivateEquityRiskModel:
        return PrivateEquityRiskModel(issuers=self.issuers)


@dataclass(frozen=True)
class PrivateEquityRiskModel:
    issuers: dict[str, PrivateEquityRiskIssuerConfig]
    label: str = "private_equity_risk"

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        rollout_count = request.rollout_count
        horizon_months = request.horizon_months
        pe_bundle_parts: list[PrivateEquityBundle] = []
        prices: dict[str, float] = {}
        for issuer_id, issuer in sorted(self.issuers.items()):
            paths = _sample_issuer(issuer_id, issuer, request)
            prices[issuer_id] = issuer.current_mark_usd
            pe_bundle_parts.append(
                PrivateEquityBundle.from_issuer_arrays(
                    issuer_id,
                    mark_usd_per_unit=paths.mark.astype(np.float64),
                    regime_code=paths.regime_code.astype(np.int64),
                    event_kind_code=paths.event_kind_code.astype(np.int64),
                    sale_opportunity_active=paths.tender_events.astype(np.bool_),
                    sale_capacity_fraction=paths.sale_capacity_fraction.astype(np.float64),
                    eligible_fraction=paths.eligible_fraction.astype(np.float64),
                    forced_sale_fraction=paths.forced_sale_fraction.astype(np.float64),
                    liquidity_blocked=(paths.liquidity_blocked >= 0.5).astype(np.bool_),
                    forced_recovery_cashout_usd=paths.forced_recovery_cashout_usd.astype(np.float64),
                    rollout_count=rollout_count,
                    horizon_months=horizon_months,
                )
            )

        sampled = SampledExogenousBundle(
            levels=SERIES_LEVELS_SCHEMA.to_frame(),
            private_equity=PrivateEquityBundle.combine(pe_bundle_parts),
            metadata={
                "exogenous_model_id": self.label,
                "private_equity_issuers": tuple(sorted(self.issuers)),
                "private_equity_prices_usd": prices,
            },
        )
        validate_sample_satisfies_request(request, sampled)
        return sampled


@dataclass(frozen=True)
class _IssuerPaths:
    mark: FloatMatrix
    tender_events: BoolMatrix
    event_kind_code: CodeMatrix
    regime_code: CodeMatrix
    sale_capacity_fraction: FloatMatrix
    eligible_fraction: FloatMatrix
    forced_sale_fraction: FloatMatrix
    liquidity_blocked: FloatMatrix
    forced_recovery_cashout_usd: FloatMatrix


def _sample_issuer(
    issuer_id: str, issuer: PrivateEquityRiskIssuerConfig, request: ExogenousSamplingRequest
) -> _IssuerPaths:
    shape = (request.rollout_count, request.horizon_months + 1)
    mark = np.full(shape, issuer.current_mark_usd, dtype=np.float64)
    tender_events = np.zeros(shape, dtype=np.bool_)
    event_kind_code = np.zeros(shape, dtype=np.int64)
    regime_code = np.full(shape, int(PrivateEquityRegimeCode.PRIVATE_OPERATING), dtype=np.int64)
    sale_capacity_fraction = np.ones(shape, dtype=np.float64)
    eligible_fraction = np.full(shape, issuer.eligible_fraction, dtype=np.float64)
    forced_sale_fraction = np.zeros(shape, dtype=np.float64)
    liquidity_blocked = np.zeros(shape, dtype=np.float64)
    forced_recovery_cashout_usd = np.zeros(shape, dtype=np.float64)

    level_seeds = derive_stream_rollout_seeds(request.rollout_seeds, stream_id=f"{issuer_id}:pe_risk_level")
    event_seeds = derive_stream_rollout_seeds(request.rollout_seeds, stream_id=f"{issuer_id}:pe_risk_event")
    for rollout_idx, (level_seed, event_seed) in enumerate(zip(level_seeds, event_seeds, strict=True)):
        latent_mark = _sample_latent_mark_path(issuer, seed=level_seed, horizon_months=request.horizon_months)
        _sample_events_into(
            issuer,
            seed=event_seed,
            latent_mark=latent_mark,
            mark=mark[rollout_idx],
            tender_events=tender_events[rollout_idx],
            event_kind_code=event_kind_code[rollout_idx],
            regime_code=regime_code[rollout_idx],
            sale_capacity_fraction=sale_capacity_fraction[rollout_idx],
            forced_sale_fraction=forced_sale_fraction[rollout_idx],
            liquidity_blocked=liquidity_blocked[rollout_idx],
            forced_recovery_cashout_usd=forced_recovery_cashout_usd[rollout_idx],
        )

    return _IssuerPaths(
        mark=mark,
        tender_events=tender_events,
        event_kind_code=event_kind_code,
        regime_code=regime_code,
        sale_capacity_fraction=sale_capacity_fraction,
        eligible_fraction=eligible_fraction,
        forced_sale_fraction=forced_sale_fraction,
        liquidity_blocked=liquidity_blocked,
        forced_recovery_cashout_usd=forced_recovery_cashout_usd,
    )


def _sample_latent_mark_path(issuer: PrivateEquityRiskIssuerConfig, *, seed: int, horizon_months: int) -> FloatMatrix:
    path = np.empty(horizon_months + 1, dtype=np.float64)
    path[0] = issuer.current_mark_usd
    if horizon_months == 0:
        return path
    rng = np.random.default_rng(seed)
    shocks = rng.standard_t(df=issuer.student_t_nu, size=horizon_months) * issuer.monthly_log_return_sigma
    log_path = math.log(issuer.current_mark_usd) + np.cumsum(issuer.monthly_log_return_mu + shocks)
    try:
        with np.errstate(over="raise", invalid="raise"):
            path[1:] = np.exp(log_path)
    except FloatingPointError as error:
        raise ValueError("private-equity risk model produced non-finite marks") from error
    if not np.all(np.isfinite(path)) or np.any(path <= 0.0):
        raise ValueError("private-equity risk model produced invalid marks")
    return path


def _sample_events_into(
    issuer: PrivateEquityRiskIssuerConfig,
    *,
    seed: int,
    latent_mark: FloatMatrix,
    mark: FloatMatrix,
    tender_events: BoolMatrix,
    event_kind_code: CodeMatrix,
    regime_code: CodeMatrix,
    sale_capacity_fraction: FloatMatrix,
    forced_sale_fraction: FloatMatrix,
    liquidity_blocked: FloatMatrix,
    forced_recovery_cashout_usd: FloatMatrix,
) -> None:
    rng = np.random.default_rng(seed)
    horizon_months = len(mark) - 1
    monthly_public = _monthly_probability(issuer.annual_public_market_probability)
    monthly_suspension = _monthly_probability(issuer.annual_liquidity_suspension_probability)
    monthly_forced_sale = _monthly_probability(issuer.annual_forced_sale_probability)
    monthly_recovery = _monthly_probability(issuer.annual_forced_recovery_probability)
    monthly_collapse = _monthly_probability(issuer.annual_collapse_probability)
    public_market = False
    acquired = False
    collapsed = False
    suspended_through = 0
    public_market_lockup_through = 0

    tender_months = _sample_event_months(
        median_months=issuer.tender_interval_months_median,
        log_sigma=issuer.tender_interval_log_sigma,
        rng=rng,
        horizon_months=horizon_months,
    )
    admin_mark_months = _sample_event_months(
        median_months=issuer.admin_mark_update_interval_months_median,
        log_sigma=issuer.admin_mark_update_interval_log_sigma,
        rng=rng,
        horizon_months=horizon_months,
    )
    for month in range(1, horizon_months + 1):
        mark[month] = mark[month - 1]
        if collapsed:
            regime_code[month] = int(PrivateEquityRegimeCode.COLLAPSED)
            liquidity_blocked[month] = 1.0
            mark[month] = mark[month - 1]
            continue

        if acquired:
            regime_code[month] = int(PrivateEquityRegimeCode.ACQUIRED)
            liquidity_blocked[month] = 1.0
            mark[month] = mark[month - 1]
            continue

        if public_market:
            regime_code[month] = int(PrivateEquityRegimeCode.PUBLIC_MARKET)
            mark[month] = latent_mark[month]
            liquidity_blocked[month] = 1.0 if month <= public_market_lockup_through else 0.0
            continue
        if month <= suspended_through:
            regime_code[month] = int(PrivateEquityRegimeCode.PRIVATE_OPERATING)
            liquidity_blocked[month] = 1.0
            continue

        event_kind = PrivateEquityEventKindCode.NONE
        if not public_market and rng.random() < monthly_recovery:
            event_kind = PrivateEquityEventKindCode.FORCED_RECOVERY
            forced_recovery_cashout_usd[month] = rng.uniform(
                issuer.forced_recovery_cashout_usd_min, issuer.forced_recovery_cashout_usd_max
            )
            regime_code[month:] = int(PrivateEquityRegimeCode.COLLAPSED)
            liquidity_blocked[month:] = 1.0
            mark[month:] = mark[month - 1] * issuer.collapsed_mark_fraction
            collapsed = True
        elif not public_market and rng.random() < monthly_collapse:
            event_kind = PrivateEquityEventKindCode.COLLAPSE
            regime_code[month:] = int(PrivateEquityRegimeCode.COLLAPSED)
            liquidity_blocked[month:] = 1.0
            mark[month:] = mark[month - 1] * issuer.collapsed_mark_fraction
            collapsed = True
        elif not public_market and rng.random() < monthly_public:
            event_kind = PrivateEquityEventKindCode.PUBLIC_MARKET_OPEN
            regime_code[month:] = int(PrivateEquityRegimeCode.PUBLIC_MARKET)
            sale_capacity_fraction[month:] = 1.0
            public_market_lockup_through = min(horizon_months, month + issuer.public_market_lockup_months - 1)
            if public_market_lockup_through >= month:
                liquidity_blocked[month : public_market_lockup_through + 1] = 1.0
            liquidity_blocked[public_market_lockup_through + 1 :] = 0.0
            mark[month] = _noisy_mark(
                latent_mark[month],
                rng=rng,
                log_noise_mu=issuer.public_market_price_log_discount_mu,
                log_noise_sigma=issuer.public_market_price_log_discount_sigma,
            )
            public_market = True
        elif not public_market and rng.random() < monthly_suspension:
            event_kind = PrivateEquityEventKindCode.LEGAL_IMPAIRMENT
            duration = int(
                rng.integers(issuer.liquidity_suspension_months_min, issuer.liquidity_suspension_months_max + 1)
            )
            suspended_through = max(suspended_through, min(horizon_months, month + duration - 1))
            regime_code[month : suspended_through + 1] = int(PrivateEquityRegimeCode.PRIVATE_OPERATING)
            liquidity_blocked[month : suspended_through + 1] = 1.0
        elif rng.random() < monthly_forced_sale:
            event_kind = PrivateEquityEventKindCode.ACQUISITION_CASHOUT
            forced_sale_fraction[month] = rng.beta(issuer.forced_sale_fraction_alpha, issuer.forced_sale_fraction_beta)
            regime_code[month:] = int(PrivateEquityRegimeCode.ACQUIRED)
            liquidity_blocked[month:] = 1.0
            mark[month] = _noisy_mark(
                latent_mark[month],
                rng=rng,
                log_noise_mu=issuer.public_market_price_log_discount_mu,
                log_noise_sigma=issuer.public_market_price_log_discount_sigma,
            )
            acquired = True
        elif not public_market and month in tender_months:
            event_kind = PrivateEquityEventKindCode.TENDER
            tender_events[month] = True
            sale_capacity_fraction[month] = rng.beta(
                issuer.tender_sale_capacity_alpha, issuer.tender_sale_capacity_beta
            )
            mark[month] = _noisy_mark(
                latent_mark[month],
                rng=rng,
                log_noise_mu=issuer.tender_price_log_discount_mu,
                log_noise_sigma=issuer.tender_price_log_discount_sigma,
            )
        elif not public_market and month in admin_mark_months:
            event_kind = PrivateEquityEventKindCode.ADMIN_MARK_UPDATE
            mark[month] = _noisy_mark(
                latent_mark[month],
                rng=rng,
                log_noise_mu=issuer.admin_mark_update_log_noise_mu,
                log_noise_sigma=issuer.admin_mark_update_log_noise_sigma,
            )

        if event_kind != PrivateEquityEventKindCode.NONE:
            event_kind_code[month] = int(event_kind)


def _sample_event_months(
    *, median_months: float, log_sigma: float, rng: np.random.Generator, horizon_months: int
) -> frozenset[int]:
    if median_months <= 0.0:
        return frozenset()
    months: set[int] = set()
    cursor_month = 0.0
    while True:
        interval = float(rng.lognormal(mean=math.log(median_months), sigma=log_sigma))
        cursor_month += max(interval, 1.0)
        month_index = round(cursor_month)
        if month_index > horizon_months:
            return frozenset(months)
        if month_index >= 1:
            months.add(month_index)


def _noisy_mark(value: float, *, rng: np.random.Generator, log_noise_mu: float, log_noise_sigma: float) -> float:
    if log_noise_mu == 0.0 and log_noise_sigma == 0.0:
        return value
    return float(value * math.exp(rng.normal(loc=log_noise_mu, scale=log_noise_sigma)))


def _monthly_probability(annual_probability: float) -> float:
    if annual_probability <= 0.0:
        return 0.0
    if annual_probability >= 1.0:
        return 1.0
    return float(1.0 - math.pow(1.0 - annual_probability, 1.0 / 12.0))
