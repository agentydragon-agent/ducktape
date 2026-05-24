"""Product-language projection request and response wire types."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from augur.api.schemas import ApiModel, Frame, Percentage

SpendIndex = Literal["none", "inflation"]
SellableBucket = Literal["public_securities"]
MetricName = Literal["cash_usd", "public_security_value_usd", "liquid_net_worth_usd", "net_worth_usd", "shortfall_usd"]
MAX_HORIZON_MONTHS = 100 * 12
DEFAULT_SELL_ORDER: tuple[SellableBucket, ...] = ("public_securities",)


class FundingPolicy(ApiModel):
    cash_buffer_trigger_below_usd: NonNegativeFloat = 0.0
    cash_buffer_sale_usd: NonNegativeFloat = 0.0
    sell_order: tuple[SellableBucket, ...] = DEFAULT_SELL_ORDER


class ScenarioKey(ApiModel):
    exogenous_model_id: str
    horizon_months: PositiveInt = Field(le=MAX_HORIZON_MONTHS)
    monthly_spend_usd: PositiveFloat
    spend_index: SpendIndex
    funding_policy: FundingPolicy = Field(default_factory=FundingPolicy)
    monthly_rent_usd: NonNegativeFloat = 0.0
    rental_location_id: str | None = None

    @model_validator(mode="after")
    def _rent_location_consistency(self) -> ScenarioKey:
        if self.monthly_rent_usd > 0 and self.rental_location_id is None:
            raise ValueError("rental_location_id is required when monthly_rent_usd > 0")
        if self.monthly_rent_usd == 0 and self.rental_location_id is not None:
            raise ValueError("rental_location_id must be unset when monthly_rent_usd == 0")
        return self


class MetricFanRequest(ApiModel):
    scenario: ScenarioKey
    rollout_seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    metric: MetricName
    percentiles: tuple[Percentage, ...] = Field(min_length=1)

    @property
    def rollout_count(self) -> int:
        return len(self.rollout_seeds)


class RolloutRequest(ApiModel):
    scenario: ScenarioKey
    seed: NonNegativeInt


class TerminalMetrics(ApiModel):
    cash_usd: float
    public_security_value_usd: NonNegativeFloat
    liquid_net_worth_usd: float
    net_worth_usd: float
    shortfall_usd: NonNegativeFloat
    failed_month_index: NonNegativeInt | None = None


class _RolloutEventBase(ApiModel):
    month_index: NonNegativeInt
    amount_usd: NonNegativeFloat


class PublicSecuritySaleEvent(_RolloutEventBase):
    kind: Literal["public_security_sale"] = "public_security_sale"
    asset_id: str
    asset_label: str | None = None
    units: NonNegativeFloat
    proceeds_usd: NonNegativeFloat
    cost_basis_usd: NonNegativeFloat


class MonthlyExpenseEvent(_RolloutEventBase):
    kind: Literal["monthly_expense"] = "monthly_expense"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class OutsideRentPaymentEvent(_RolloutEventBase):
    kind: Literal["outside_rent"] = "outside_rent"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class TaxAccrualEvent(_RolloutEventBase):
    kind: Literal["tax_accrual"] = "tax_accrual"
    jurisdiction_id: str
    tax_year_end_month: NonNegativeInt
    ordinary_income_usd: float
    ltcg_usd: float
    stcg_usd: float
    ordinary_tax_usd: NonNegativeFloat
    capital_gain_tax_usd: NonNegativeFloat
    total_tax_usd: NonNegativeFloat


class TaxPaymentEvent(_RolloutEventBase):
    kind: Literal["tax_payment"] = "tax_payment"
    obligation_type: str
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


class RolloutFailureEvent(_RolloutEventBase):
    kind: Literal["failure"] = "failure"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


type RolloutEvent = Annotated[
    PublicSecuritySaleEvent
    | MonthlyExpenseEvent
    | OutsideRentPaymentEvent
    | TaxAccrualEvent
    | TaxPaymentEvent
    | RolloutFailureEvent,
    Field(discriminator="kind"),
]


class RolloutOutput(ApiModel):
    seed: NonNegativeInt
    failed: bool
    monthly_metrics: Frame
    terminal_metrics: TerminalMetrics
    events: tuple[RolloutEvent, ...] = ()


class RolloutSummary(ApiModel):
    seed: NonNegativeInt
    failed: bool
    terminal_metrics: TerminalMetrics
    sort_rank: NonNegativeInt
    rank_percentile: Percentage


class MetricFanResponse(ApiModel):
    exogenous_model_id: str
    metric: MetricName
    monthly_metric_fan: Frame
    terminal_metric_percentiles: Frame
    rollout_summaries: tuple[RolloutSummary, ...]
    failed_count: NonNegativeInt
    diagnostics: tuple[str, ...] = ()


class RolloutResponse(ApiModel):
    exogenous_model_id: str
    rollout: RolloutOutput
    diagnostics: tuple[str, ...] = ()
