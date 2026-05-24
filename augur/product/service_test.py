from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import pytest_bazel
from more_itertools import one

from augur.api.catalog import build_bootstrap_payload
from augur.api.config import Config, load_augur_config
from augur.model.exogenous import ExogenousPathModel, ExogenousSamplingRequest, SampledExogenousBundle
from augur.model.series import SP500_SERIES_ID
from augur.product import decode, service
from augur.product.scenarios import resolve_primary_agent_id
from augur.product.service import ProductService
from augur.product.wire import (
    FundingPolicy,
    MetricFanRequest,
    MonthlyExpenseEvent,
    OutsideRentPaymentEvent,
    PublicSecuritySaleEvent,
    RolloutFailureEvent,
    RolloutRequest,
    ScenarioKey,
)
from util.bazel.runfiles import get_required_path


@dataclass
class CountingExogenousModel:
    inner: ExogenousPathModel
    sample_requests: list[ExogenousSamplingRequest] = field(default_factory=list)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        self.sample_requests.append(request)
        return self.inner.sample(request)


def _augur_config() -> Config:
    return load_augur_config(get_required_path("_main/augur/api/testdata/config.yaml"))


@pytest.fixture
def counting_exogenous_model() -> CountingExogenousModel:
    return CountingExogenousModel(inner=_augur_config().exogenous_provider.realize_model())


def _service(model: CountingExogenousModel, *, augur_config: Config | None = None) -> ProductService:
    config = augur_config or _augur_config()
    bootstrap = build_bootstrap_payload(config)
    return ProductService(
        portfolio=config.portfolio,
        initial_cash_usd=float(config.snapshot.cash_usd),
        primary_agent_id=resolve_primary_agent_id(config),
        known_location_ids=frozenset(location.id for location in bootstrap.locations),
        exogenous_model=model,
        max_rollout_samples=config.max_rollout_samples,
        max_cache_rollouts=10,
    )


def _scenario_key() -> ScenarioKey:
    return ScenarioKey(
        exogenous_model_id="current_exogenous_model", horizon_months=3, monthly_spend_usd=1_000.0, spend_index="none"
    )


def test_metric_fan_and_rollout_detail_share_cached_sim_rollouts(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    scenario = _scenario_key()

    fan = product.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="cash_usd", percentiles=(0, 50, 100))
    )

    assert [request.rollout_seeds for request in counting_exogenous_model.sample_requests] == [(7, 8)]
    assert counting_exogenous_model.sample_requests[0].required_level_series == frozenset({SP500_SERIES_ID})
    assert fan.exogenous_model_id == "independent_exogenous_model"
    assert fan.metric == "cash_usd"
    assert fan.failed_count == 0
    assert [summary.seed for summary in fan.rollout_summaries] == [7, 8]
    assert [summary.sort_rank for summary in fan.rollout_summaries] == [0, 1]
    assert [summary.rank_percentile for summary in fan.rollout_summaries] == [25.0, 75.0]
    assert [summary.terminal_metrics.cash_usd for summary in fan.rollout_summaries] == [247_000.0, 247_000.0]
    assert len(fan.monthly_metric_fan["month_index"]) == 12
    assert fan.monthly_metric_fan["month_index"] == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]
    assert fan.monthly_metric_fan["percentile"] == [0.0, 50.0, 100.0] * 4
    assert fan.monthly_metric_fan["value"] == [
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
    assert fan.terminal_metric_percentiles == {"percentile": [0.0, 50.0, 100.0], "value": [247_000.0] * 3}

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert [request.rollout_seeds for request in counting_exogenous_model.sample_requests] == [(7, 8)]
    assert detail.exogenous_model_id == "independent_exogenous_model"
    assert detail.rollout.seed == 7
    assert detail.rollout.monthly_metrics["cash_usd"] == [250_000.0, 249_000.0, 248_000.0, 247_000.0]
    assert detail.rollout.monthly_metrics["public_security_value_usd"][0] == 750_000.0
    assert detail.rollout.monthly_metrics["liquid_net_worth_usd"][0] == 1_000_000.0
    assert detail.rollout.monthly_metrics["net_worth_usd"][0] == 1_000_000.0
    assert [event.kind for event in detail.rollout.events] == ["monthly_expense"] * 3
    assert [event.amount_paid_usd for event in detail.rollout.events if event.kind == "monthly_expense"] == [
        1_000.0,
        1_000.0,
        1_000.0,
    ]

    public_security_fan = product.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="public_security_value_usd", percentiles=(50,))
    )

    assert public_security_fan.monthly_metric_fan["value"][0] == 750_000.0

    fan_with_one_new_seed = product.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8, 9), metric="cash_usd", percentiles=(50,))
    )

    assert [request.rollout_seeds for request in counting_exogenous_model.sample_requests] == [(7, 8), (9,)]
    assert fan_with_one_new_seed.monthly_metric_fan["percentile"] == [50.0] * 4


def test_metric_fan_decodes_each_rollout_once_per_batch(
    counting_exogenous_model: CountingExogenousModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = _service(counting_exogenous_model)
    scenario = _scenario_key()
    original = decode.monthly_metrics_for_rollout
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "monthly_metrics_for_rollout", counted)

    product.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8, 9, 10), metric="cash_usd", percentiles=(50,))
    )

    assert calls == 4


def test_metric_fan_does_not_materialize_rollout_events(
    counting_exogenous_model: CountingExogenousModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = _service(counting_exogenous_model)
    scenario = _scenario_key()

    def fail_rollout_events(*_args, **_kwargs):
        raise AssertionError("metric fan should not build selected-rollout event detail")

    monkeypatch.setattr(service, "rollout_events_from", fail_rollout_events)

    product.metric_fan(MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="cash_usd", percentiles=(50,)))


def test_failed_rollout_metrics_freeze_at_zero_after_failure(counting_exogenous_model: CountingExogenousModel) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=3,
        monthly_spend_usd=300_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
    )

    fan = product.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7,), metric="net_worth_usd", percentiles=(50,))
    )

    assert fan.failed_count == 1
    assert fan.monthly_metric_fan["month_index"] == [0, 1, 2, 3]
    assert fan.monthly_metric_fan["value"] == [1_000_000.0, 0.0, 0.0, 0.0]
    [summary] = fan.rollout_summaries
    assert summary.failed is True
    assert summary.terminal_metrics.failed_month_index == 0
    assert summary.terminal_metrics.cash_usd == 0.0
    assert summary.terminal_metrics.public_security_value_usd == 0.0
    assert summary.terminal_metrics.net_worth_usd == 0.0
    assert summary.terminal_metrics.shortfall_usd == 300_000.0

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert detail.rollout.failed is True
    assert detail.rollout.monthly_metrics["cash_usd"] == [250_000.0, 0.0, 0.0, 0.0]
    assert detail.rollout.monthly_metrics["public_security_value_usd"] == [750_000.0, 0.0, 0.0, 0.0]
    assert detail.rollout.monthly_metrics["net_worth_usd"] == [1_000_000.0, 0.0, 0.0, 0.0]
    assert [event.kind for event in detail.rollout.events] == ["monthly_expense", "failure"]
    expense, failure = detail.rollout.events
    assert isinstance(expense, MonthlyExpenseEvent)
    assert isinstance(failure, RolloutFailureEvent)
    assert expense.amount_paid_usd == 0.0
    assert expense.shortfall_usd == 300_000.0
    assert failure.shortfall_usd == 300_000.0


def test_default_funding_policy_sells_public_securities_for_required_spend(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model", horizon_months=1, monthly_spend_usd=300_000.0, spend_index="none"
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert detail.rollout.failed is False
    columns = detail.rollout.monthly_metrics
    assert columns["cash_usd"] == [250_000.0, 0.0]
    public_security_value_usd = columns["public_security_value_usd"]
    assert public_security_value_usd[0] == 750_000.0
    terminal_public_security_value_usd = float(public_security_value_usd[1])  # type: ignore[arg-type]
    assert 0.0 < terminal_public_security_value_usd < 750_000.0
    assert detail.rollout.terminal_metrics.cash_usd == 0.0
    assert detail.rollout.terminal_metrics.shortfall_usd == 0.0
    assert detail.rollout.terminal_metrics.net_worth_usd == pytest.approx(terminal_public_security_value_usd)
    assert [event.kind for event in detail.rollout.events] == ["public_security_sale", "monthly_expense"]
    sale, expense = detail.rollout.events
    assert isinstance(sale, PublicSecuritySaleEvent)
    assert isinstance(expense, MonthlyExpenseEvent)
    assert sale.asset_label == "SP500 Proxy (VOO)"
    assert sale.proceeds_usd == pytest.approx(50_000.0)
    assert sale.units == pytest.approx(100.0)
    assert expense.amount_due_usd == 300_000.0
    assert expense.amount_paid_usd == 300_000.0
    assert expense.shortfall_usd == 0.0


def test_product_cash_buffer_uses_sim_trigger_and_fixed_sale_amount(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=1,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(cash_buffer_trigger_below_usd=260_000.0, cash_buffer_sale_usd=20_000.0),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert detail.rollout.failed is False
    assert detail.rollout.monthly_metrics["cash_usd"] == [250_000.0, 269_000.0]
    assert detail.rollout.terminal_metrics.cash_usd == 269_000.0
    assert detail.rollout.terminal_metrics.shortfall_usd == 0.0
    assert [event.kind for event in detail.rollout.events] == ["public_security_sale", "monthly_expense"]
    sale, expense = detail.rollout.events
    assert isinstance(sale, PublicSecuritySaleEvent)
    assert isinstance(expense, MonthlyExpenseEvent)
    assert sale.proceeds_usd == pytest.approx(20_000.0)
    assert expense.amount_paid_usd == 1_000.0


def test_product_rollout_includes_zero_tax_accrual_events_without_taxable_income(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=12,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    tax_accruals = [event for event in detail.rollout.events if event.kind == "tax_accrual"]
    assert {event.jurisdiction_id for event in tax_accruals} == {"federal_us", "california"}
    assert {event.month_index for event in tax_accruals} == {11}
    assert all(event.amount_usd == 0.0 for event in tax_accruals)
    assert [event for event in detail.rollout.events if event.kind == "tax_payment"] == []


def test_product_rollout_includes_federal_and_california_tax_events_for_public_security_sales(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=13,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(cash_buffer_trigger_below_usd=260_000.0, cash_buffer_sale_usd=500_000.0),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    events = detail.rollout.events
    tax_accruals = [event for event in events if event.kind == "tax_accrual"]
    assert {event.jurisdiction_id for event in tax_accruals} == {"federal_us", "california"}
    assert {event.month_index for event in tax_accruals} == {11}
    assert all(event.amount_usd > 0 for event in tax_accruals)
    assert sum(event.amount_usd for event in tax_accruals) == pytest.approx(
        sum(event.total_tax_usd for event in tax_accruals)
    )
    federal = one(event for event in tax_accruals if event.jurisdiction_id == "federal_us")
    california = one(event for event in tax_accruals if event.jurisdiction_id == "california")
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


def test_outside_rent_emits_yearly_re_pegged_obligation(counting_exogenous_model: CountingExogenousModel) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=14,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        monthly_rent_usd=3_000.0,
        rental_location_id="location_a",
        funding_policy=FundingPolicy(sell_order=()),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    rent_events = [event for event in detail.rollout.events if event.kind == "outside_rent"]
    # 14 monthly rent payments — one per event month.
    assert len(rent_events) == 14
    assert all(isinstance(event, OutsideRentPaymentEvent) for event in rent_events)
    # Year 0 (months 0..11) all peg at the base amount: rent_series[0]/rent_series[0] = 1.
    year_zero = [event for event in rent_events if event.month_index < 12]
    assert {event.amount_paid_usd for event in year_zero} == {3_000.0}
    # Year 1 (months 12..) rescales by rent_series[12]/rent_series[0] — stochastic, so non-3000.
    year_one = [event for event in rent_events if event.month_index >= 12]
    assert year_one
    assert all(event.amount_paid_usd != 3_000.0 for event in year_one)
    # Within year 1 the amount stays flat.
    assert len({event.amount_paid_usd for event in year_one}) == 1
    # Required-level-series for the request should include the location-keyed rent series.
    assert "rent:location_a" in counting_exogenous_model.sample_requests[0].required_level_series

    # Year-0 cash drops by spend + rent = 4000 each month deterministically.
    cash = detail.rollout.monthly_metrics["cash_usd"]
    assert cash[0] == 250_000.0
    assert cash[12] == pytest.approx(250_000.0 - 12 * 4_000.0)
    # Monthly_expense events are still emitted alongside, distinctly from outside_rent.
    expense_events = [event for event in detail.rollout.events if event.kind == "monthly_expense"]
    assert len(expense_events) == 14
    assert all(event.amount_paid_usd == 1_000.0 for event in expense_events)


def test_outside_rent_zero_omits_rent_series_requirement(counting_exogenous_model: CountingExogenousModel) -> None:
    product = _service(counting_exogenous_model)
    scenario = _scenario_key()  # no rent

    product.metric_fan(MetricFanRequest(scenario=scenario, rollout_seeds=(7,), metric="cash_usd", percentiles=(50,)))

    assert not any(
        "rent:" in series_id for series_id in counting_exogenous_model.sample_requests[0].required_level_series
    )


def test_outside_rent_rejects_unknown_location(counting_exogenous_model: CountingExogenousModel) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=3,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        monthly_rent_usd=3_000.0,
        rental_location_id="not_a_real_location",
    )

    with pytest.raises(ValueError, match=r"unknown rental_location_id"):
        product.rollout(RolloutRequest(scenario=scenario, seed=7))


def test_scenario_key_rejects_rent_without_location() -> None:
    with pytest.raises(ValueError, match=r"rental_location_id is required"):
        ScenarioKey(
            exogenous_model_id="current_exogenous_model",
            horizon_months=3,
            monthly_spend_usd=1_000.0,
            spend_index="none",
            monthly_rent_usd=3_000.0,
        )


def test_scenario_key_rejects_location_without_rent() -> None:
    with pytest.raises(ValueError, match=r"rental_location_id must be unset"):
        ScenarioKey(
            exogenous_model_id="current_exogenous_model",
            horizon_months=3,
            monthly_spend_usd=1_000.0,
            spend_index="none",
            rental_location_id="location_a",
        )


if __name__ == "__main__":
    pytest_bazel.main()
