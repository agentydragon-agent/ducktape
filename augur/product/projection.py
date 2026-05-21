"""Product-language projection request and response wire types."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, PositiveFloat, PositiveInt, model_validator

from augur.api.schemas import ApiModel, ColumnarTable

Percentile = Annotated[int, Field(ge=0, le=100)]
SpendIndex = Literal["none", "inflation"]


class ProductMetric(StrEnum):
    CASH_USD = "cash_usd"
    NET_WORTH_USD = "net_worth_usd"
    SHORTFALL_USD = "shortfall_usd"


class ProjectionRequest(ApiModel):
    exogenous_model_id: str = "current_exogenous_model"
    horizon_months: PositiveInt
    rollout_seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)
    percentiles: tuple[Percentile, ...] = (5, 25, 50, 75, 95)
    monthly_spend_usd: PositiveFloat
    spend_index: SpendIndex = "inflation"

    @property
    def rollout_count(self) -> int:
        return len(self.rollout_seeds)

    @model_validator(mode="after")
    def _percentiles_are_nonempty(self) -> ProjectionRequest:
        if not self.percentiles:
            raise ValueError("percentiles must be non-empty")
        return self


class MetricTable(ApiModel):
    metric: ProductMetric
    table: ColumnarTable


class RolloutOutput(ApiModel):
    seed: NonNegativeInt
    failed: bool
    monthly_metric_tables: tuple[MetricTable, ...]
    terminal_metrics: ColumnarTable


class ProjectionResponse(ApiModel):
    exogenous_model_id: str
    horizon_months: NonNegativeInt
    rollouts: tuple[RolloutOutput, ...] = Field(min_length=1)
    diagnostics: tuple[str, ...] = ()
