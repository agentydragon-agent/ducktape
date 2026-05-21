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


class ProductSamplingRequest(ApiModel):
    exogenous_model_id: str = "current_exogenous_model"
    horizon_months: PositiveInt
    rollout_seeds: tuple[NonNegativeInt, ...] = Field(min_length=1)

    @property
    def rollout_count(self) -> int:
        return len(self.rollout_seeds)


class ProductReportSpec(ApiModel):
    percentiles: tuple[Percentile, ...] = (5, 25, 50, 75, 95)

    @model_validator(mode="after")
    def _percentiles_are_nonempty(self) -> ProductReportSpec:
        if not self.percentiles:
            raise ValueError("percentiles must be non-empty")
        return self


class CashSpendCase(ApiModel):
    case_type: Literal["cash_spend"] = "cash_spend"
    monthly_spend_usd: PositiveFloat
    spend_index: SpendIndex = "inflation"


class ProductScenario(ApiModel):
    scenario_id: str
    label: str
    case: CashSpendCase


class ProjectionRequest(ApiModel):
    sampling: ProductSamplingRequest
    report: ProductReportSpec = Field(default_factory=ProductReportSpec)
    scenarios: tuple[ProductScenario, ...] = Field(min_length=1)


class ProductSamplingSummary(ApiModel):
    exogenous_model_id: str
    rollout_count: NonNegativeInt
    horizon_months: NonNegativeInt
    rollout_seeds: tuple[NonNegativeInt, ...]
    source_metadata: dict[str, object] = Field(default_factory=dict)


class RolloutHealthSummary(ApiModel):
    rollout_count: NonNegativeInt
    active_count: NonNegativeInt
    cash_negative_count: NonNegativeInt
    failed_count: NonNegativeInt

    @model_validator(mode="after")
    def _counts_do_not_exceed_rollouts(self) -> RolloutHealthSummary:
        counted = self.active_count + self.cash_negative_count + self.failed_count
        if counted > self.rollout_count:
            raise ValueError("rollout status counts must not exceed rollout_count")
        return self


class ProductMetricFan(ApiModel):
    metric: ProductMetric
    table: ColumnarTable


class ProductDistributionView(ApiModel):
    metric_fans: tuple[ProductMetricFan, ...]
    terminal_metrics: ColumnarTable


class ProductDiagnostic(ApiModel):
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    scenario_id: str | None = None
    field_path: tuple[str, ...] = ()


class ProductScenarioResult(ApiModel):
    scenario_id: str
    label: str
    accepted: bool
    rollout_health: RolloutHealthSummary | None = None
    distribution: ProductDistributionView | None = None
    diagnostics: tuple[ProductDiagnostic, ...] = ()


class ProjectionResponse(ApiModel):
    projection_run_id: str
    sampling: ProductSamplingSummary
    scenarios: tuple[ProductScenarioResult, ...]
    diagnostics: tuple[ProductDiagnostic, ...] = ()
