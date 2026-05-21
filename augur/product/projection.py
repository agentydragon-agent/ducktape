"""Product-language projection request and response wire types."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt

from augur.api.schemas import ApiModel, ColumnarTable

SpendIndex = Literal["none", "inflation"]
MAX_HORIZON_MONTHS = 100 * 12


class ProjectionRequest(ApiModel):
    exogenous_model_id: str
    horizon_months: PositiveInt = Field(le=MAX_HORIZON_MONTHS)
    rollout_seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    monthly_spend_usd: PositiveFloat
    spend_index: SpendIndex

    @property
    def rollout_count(self) -> int:
        return len(self.rollout_seeds)


class TerminalMetrics(ApiModel):
    cash_usd: float
    net_worth_usd: float
    drawdown_usd: NonNegativeFloat
    shortfall_usd: NonNegativeFloat
    failed_month_index: NonNegativeInt | None = None


class RolloutOutput(ApiModel):
    seed: NonNegativeInt
    failed: bool
    monthly_metrics: ColumnarTable
    terminal_metrics: TerminalMetrics


class ProjectionResponse(ApiModel):
    exogenous_model_id: str
    horizon_months: NonNegativeInt
    rollouts: tuple[RolloutOutput, ...] = Field(min_length=1)
    diagnostics: tuple[str, ...] = ()
