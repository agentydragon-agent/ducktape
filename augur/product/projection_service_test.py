from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import pytest_bazel

import augur.product.projection_service as projection_service_module
from augur.api.config import load_augur_config
from augur.model.exogenous import ExogenousSamplingRequest, SampledExogenousBundle
from augur.model.series import SP500_SERIES_ID
from augur.model.simple_exogenous import SimpleExogenousModel
from augur.product.projection import (
    FundingPolicy,
    MetricFanRequest,
    MonthlyExpenseEvent,
    PublicSecuritySaleEvent,
    RolloutFailureEvent,
    RolloutRequest,
    ScenarioKey,
)
from augur.product.projection_service import ProductProjectionCache, ProductProjectionService
from util.bazel.runfiles import get_required_path


@dataclass
class CountingExogenousModel:
    sample_requests: list[ExogenousSamplingRequest] = field(default_factory=list)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        self.sample_requests.append(request)
        return SimpleExogenousModel().sample(request)


def _service(model: CountingExogenousModel) -> ProductProjectionService:
    return ProductProjectionService(
        augur_config=load_augur_config(get_required_path("_main/augur/api/testdata/config.yaml")),
        exogenous_model=model,
        cache=ProductProjectionCache(max_rollouts=10),
    )


def _scenario_key() -> ScenarioKey:
    return ScenarioKey(
        exogenous_model_id="current_exogenous_model", horizon_months=3, monthly_spend_usd=1_000.0, spend_index="none"
    )


def test_metric_fan_and_rollout_detail_share_cached_sim_rollouts() -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = _scenario_key()

    fan = service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="cash_usd", percentiles=(0, 50, 100))
    )

    assert [request.rollout_seeds for request in model.sample_requests] == [(7, 8)]
    assert model.sample_requests[0].required_level_series == frozenset({SP500_SERIES_ID})
    assert fan.exogenous_model_id == "simple_exogenous_model"
    assert fan.metric == "cash_usd"
    assert fan.failed_count == 0
    assert [summary.seed for summary in fan.rollout_summaries] == [7, 8]
    assert [summary.sort_rank for summary in fan.rollout_summaries] == [0, 1]
    assert [summary.rank_percentile for summary in fan.rollout_summaries] == [25.0, 75.0]
    assert [summary.terminal_metrics.cash_usd for summary in fan.rollout_summaries] == [247_000.0, 247_000.0]
    assert fan.monthly_metric_fan.row_count == 12
    assert fan.monthly_metric_fan.columns["month_index"] == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]
    assert fan.monthly_metric_fan.columns["percentile"] == [0.0, 50.0, 100.0] * 4
    assert fan.monthly_metric_fan.columns["value"] == [
        250_000.0,
        250_000.0,
        250_000.0,
        249_000.0,
        249_000.0,
        249_000.0,
        248_000.0,
        248_000.0,
        248_000.0,
        247_000.0,
        247_000.0,
        247_000.0,
    ]
    assert fan.terminal_metric_percentiles.columns == {"percentile": [0.0, 50.0, 100.0], "value": [247_000.0] * 3}

    detail = service.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert [request.rollout_seeds for request in model.sample_requests] == [(7, 8)]
    assert detail.exogenous_model_id == "simple_exogenous_model"
    assert detail.rollout.seed == 7
    assert detail.rollout.monthly_metrics.columns["cash_usd"] == [250_000.0, 249_000.0, 248_000.0, 247_000.0]
    assert detail.rollout.monthly_metrics.columns["public_security_value_usd"][0] == 750_000.0
    assert detail.rollout.monthly_metrics.columns["liquid_net_worth_usd"][0] == 1_000_000.0
    assert detail.rollout.monthly_metrics.columns["net_worth_usd"][0] == 1_000_000.0
    assert [event.kind for event in detail.rollout.events] == ["monthly_expense"] * 3
    assert [event.amount_paid_usd for event in detail.rollout.events if event.kind == "monthly_expense"] == [
        1_000.0,
        1_000.0,
        1_000.0,
    ]

    public_security_fan = service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="public_security_value_usd", percentiles=(50,))
    )

    assert public_security_fan.monthly_metric_fan.columns["value"][0] == 750_000.0

    fan_with_one_new_seed = service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8, 9), metric="cash_usd", percentiles=(50,))
    )

    assert [request.rollout_seeds for request in model.sample_requests] == [(7, 8), (9,)]
    assert fan_with_one_new_seed.monthly_metric_fan.columns["percentile"] == [50.0] * 4


def test_metric_fan_projects_monthly_metrics_once_per_missing_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = _scenario_key()
    original_project_net_worth = projection_service_module.project_net_worth
    calls = 0

    def counted_project_net_worth(run):
        nonlocal calls
        calls += 1
        return original_project_net_worth(run)

    monkeypatch.setattr(projection_service_module, "project_net_worth", counted_project_net_worth)

    service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8, 9, 10), metric="cash_usd", percentiles=(50,))
    )

    assert calls == 1


def test_metric_fan_does_not_materialize_rollout_events(monkeypatch: pytest.MonkeyPatch) -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = _scenario_key()

    def fail_rollout_events(*_args, **_kwargs):
        raise AssertionError("metric fan should not build selected-rollout event detail")

    monkeypatch.setattr(projection_service_module, "_rollout_events", fail_rollout_events)

    service.metric_fan(MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="cash_usd", percentiles=(50,)))


def test_failed_rollout_metrics_freeze_at_zero_after_failure() -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=3,
        monthly_spend_usd=300_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
    )

    fan = service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7,), metric="net_worth_usd", percentiles=(50,))
    )

    assert fan.failed_count == 1
    assert fan.monthly_metric_fan.columns["month_index"] == [0, 1, 2, 3]
    assert fan.monthly_metric_fan.columns["value"] == [1_000_000.0, 0.0, 0.0, 0.0]
    [summary] = fan.rollout_summaries
    assert summary.failed is True
    assert summary.terminal_metrics.failed_month_index == 0
    assert summary.terminal_metrics.cash_usd == 0.0
    assert summary.terminal_metrics.public_security_value_usd == 0.0
    assert summary.terminal_metrics.net_worth_usd == 0.0
    assert summary.terminal_metrics.shortfall_usd == 300_000.0

    detail = service.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert detail.rollout.failed is True
    assert detail.rollout.monthly_metrics.columns["cash_usd"] == [250_000.0, 0.0, 0.0, 0.0]
    assert detail.rollout.monthly_metrics.columns["public_security_value_usd"] == [750_000.0, 0.0, 0.0, 0.0]
    assert detail.rollout.monthly_metrics.columns["net_worth_usd"] == [1_000_000.0, 0.0, 0.0, 0.0]
    assert [event.kind for event in detail.rollout.events] == ["monthly_expense", "failure"]
    expense, failure = detail.rollout.events
    assert isinstance(expense, MonthlyExpenseEvent)
    assert isinstance(failure, RolloutFailureEvent)
    assert expense.amount_paid_usd == 0.0
    assert expense.shortfall_usd == 300_000.0
    assert failure.shortfall_usd == 300_000.0


def test_default_funding_policy_sells_public_securities_for_required_spend() -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model", horizon_months=1, monthly_spend_usd=300_000.0, spend_index="none"
    )

    detail = service.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert detail.rollout.failed is False
    columns = detail.rollout.monthly_metrics.columns
    assert columns["cash_usd"] == [250_000.0, 0.0]
    assert columns["public_security_value_usd"][0] == 750_000.0
    assert 0.0 < columns["public_security_value_usd"][1] < 750_000.0
    assert detail.rollout.terminal_metrics.cash_usd == 0.0
    assert detail.rollout.terminal_metrics.shortfall_usd == 0.0
    assert detail.rollout.terminal_metrics.net_worth_usd == pytest.approx(columns["public_security_value_usd"][1])
    assert [event.kind for event in detail.rollout.events] == ["public_security_sale", "monthly_expense"]
    sale, expense = detail.rollout.events
    assert isinstance(sale, PublicSecuritySaleEvent)
    assert isinstance(expense, MonthlyExpenseEvent)
    assert sale.label == "Sold SP500 Proxy (VOO)"
    assert sale.proceeds_usd == pytest.approx(50_000.0)
    assert sale.units == pytest.approx(100.0)
    assert expense.amount_due_usd == 300_000.0
    assert expense.amount_paid_usd == 300_000.0
    assert expense.shortfall_usd == 0.0


def test_product_cash_buffer_uses_sim_trigger_and_fixed_sale_amount() -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=1,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(cash_buffer_trigger_below_usd=260_000.0, cash_buffer_sale_usd=20_000.0),
    )

    detail = service.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert detail.rollout.failed is False
    assert detail.rollout.monthly_metrics.columns["cash_usd"] == [250_000.0, 269_000.0]
    assert detail.rollout.terminal_metrics.cash_usd == 269_000.0
    assert detail.rollout.terminal_metrics.shortfall_usd == 0.0
    assert [event.kind for event in detail.rollout.events] == ["public_security_sale", "monthly_expense"]
    sale, expense = detail.rollout.events
    assert isinstance(sale, PublicSecuritySaleEvent)
    assert isinstance(expense, MonthlyExpenseEvent)
    assert sale.proceeds_usd == pytest.approx(20_000.0)
    assert expense.amount_paid_usd == 1_000.0


def test_product_rollout_includes_zero_tax_accrual_events_without_taxable_income() -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=12,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
    )

    detail = service.rollout(RolloutRequest(scenario=scenario, seed=7))

    tax_accruals = [event for event in detail.rollout.events if event.kind == "tax_accrual"]
    assert {event.jurisdiction_id for event in tax_accruals} == {"federal_us", "california"}
    assert {event.month_index for event in tax_accruals} == {11}
    assert all(event.amount_usd == 0.0 for event in tax_accruals)
    assert [event for event in detail.rollout.events if event.kind == "tax_payment"] == []


def test_product_rollout_includes_federal_and_california_tax_events_for_public_security_sales() -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=13,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(cash_buffer_trigger_below_usd=260_000.0, cash_buffer_sale_usd=500_000.0),
    )

    detail = service.rollout(RolloutRequest(scenario=scenario, seed=7))

    events = detail.rollout.events
    tax_accruals = [event for event in events if event.kind == "tax_accrual"]
    assert {event.jurisdiction_id for event in tax_accruals} == {"federal_us", "california"}
    assert {event.month_index for event in tax_accruals} == {11}
    assert all(event.amount_usd > 0 for event in tax_accruals)
    assert sum(event.amount_usd for event in tax_accruals) == pytest.approx(
        sum(event.total_tax_usd for event in tax_accruals)
    )
    federal = next(event for event in tax_accruals if event.jurisdiction_id == "federal_us")
    california = next(event for event in tax_accruals if event.jurisdiction_id == "california")
    assert federal.capital_gain_tax_usd > 0
    assert california.capital_gain_tax_usd == 0.0
    assert california.ordinary_tax_usd > 0

    tax_payments = [event for event in events if event.kind == "tax_payment"]
    [tax_payment] = tax_payments
    assert tax_payment.month_index == 12
    assert tax_payment.obligation_type == "tax_true_up"
    assert tax_payment.amount_due_usd == pytest.approx(sum(event.amount_usd for event in tax_accruals))
    assert tax_payment.amount_paid_usd == pytest.approx(tax_payment.amount_due_usd)
    assert tax_payment.shortfall_usd == 0.0


if __name__ == "__main__":
    pytest_bazel.main()
