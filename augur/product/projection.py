"""Product-language projection request and response wire types."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt

from augur.api.schemas import ApiModel, ColumnarTable, Percentage

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
    label: str
    amount_usd: NonNegativeFloat
    detail: str = ""


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


class RolloutFailureEvent(_RolloutEventBase):
    kind: Literal["failure"] = "failure"
    amount_due_usd: NonNegativeFloat
    amount_paid_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat


type RolloutEvent = Annotated[
    PublicSecuritySaleEvent | MonthlyExpenseEvent | RolloutFailureEvent, Field(discriminator="kind")
]


class RolloutOutput(ApiModel):
    seed: NonNegativeInt
    failed: bool
    monthly_metrics: ColumnarTable
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
    monthly_metric_fan: ColumnarTable
    terminal_metric_percentiles: ColumnarTable
    rollout_summaries: tuple[RolloutSummary, ...]
    failed_count: NonNegativeInt
    diagnostics: tuple[str, ...] = ()


class RolloutResponse(ApiModel):
    exogenous_model_id: str
    rollout: RolloutOutput
    diagnostics: tuple[str, ...] = ()
