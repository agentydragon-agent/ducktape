"""Product-language projection request and response wire types."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt

from augur.api.schemas import ApiModel, ColumnarTable, Percentage

SpendIndex = Literal["none", "inflation"]
MetricName = Literal[
    "cash_usd", "public_security_value_usd", "liquid_net_worth_usd", "net_worth_usd", "drawdown_usd", "shortfall_usd"
]
MAX_HORIZON_MONTHS = 100 * 12


class ScenarioKey(ApiModel):
    exogenous_model_id: str
    horizon_months: PositiveInt = Field(le=MAX_HORIZON_MONTHS)
    monthly_spend_usd: PositiveFloat
    spend_index: SpendIndex


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
    drawdown_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat
    failed_month_index: NonNegativeInt | None = None


class RolloutOutput(ApiModel):
    seed: NonNegativeInt
    failed: bool
    monthly_metrics: ColumnarTable
    terminal_metrics: TerminalMetrics


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
