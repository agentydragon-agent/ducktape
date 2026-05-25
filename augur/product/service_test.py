from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import pytest_bazel
from more_itertools import one

from augur.api.catalog import build_bootstrap_payload
from augur.api.config import Config, load_augur_config
from augur.model.exogenous import ExogenousSamplingRequest, SampledExogenousBundle, Sampler
from augur.model.series import INFLATION_SERIES_ID, SP500_SERIES_ID
from augur.product import decode, service
from augur.product.scenarios import resolve_primary_agent_id
from augur.product.service import ProductService
from augur.product.wire import (
    CashFinancing,
    ClosingCostPaymentEvent,
    FundingPolicy,
    HoaDuesPaymentEvent,
    HoldingSaleEvent,
    HomeownersInsurancePaymentEvent,
    MetricFanRequest,
    MonthlyExpenseEvent,
    MortgageFinancing,
    MortgagePaymentEvent,
    OutsideRentPaymentEvent,
    PropertyMaintenancePaymentEvent,
    PropertyPurchase,
    PropertyPurchaseEvent,
    PropertyTaxPaymentEvent,
    RolloutFailureEvent,
    RolloutRequest,
    ScenarioKey,
)
from util.bazel.runfiles import get_required_path


@dataclass
class CountingExogenousModel:
    inner: Sampler
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
        properties_by_id={property_.id: property_ for property_ in bootstrap.properties},
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
    assert counting_exogenous_model.sample_requests[0].required_level_series == frozenset(
        {SP500_SERIES_ID, "crypto:btc", "crypto:eth", "private_equity:private_holding_a"}
    )
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
    assert detail.rollout.monthly_metrics["holding_value_usd"][0] == 750_000.0
    assert detail.rollout.monthly_metrics["liquid_net_worth_usd"][0] == 1_000_000.0
    # +$25k for the PHA private-equity position (1000 units at $25 anchor).
    assert detail.rollout.monthly_metrics["net_worth_usd"][0] == 1_025_000.0
    assert [event.kind for event in detail.rollout.events] == ["monthly_expense"] * 3
    assert [event.amount_paid_usd for event in detail.rollout.events if event.kind == "monthly_expense"] == [
        1_000.0,
        1_000.0,
        1_000.0,
    ]

    holding_fan = product.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="holding_value_usd", percentiles=(50,))
    )

    assert holding_fan.monthly_metric_fan["value"][0] == 750_000.0

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
    original = decode.monthly_metric_arrays
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "monthly_metric_arrays", counted)

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
    # Month 0 = cash 250k + holdings 750k + PHA 25k; failure zeros subsequent months.
    assert fan.monthly_metric_fan["value"] == [1_025_000.0, 0.0, 0.0, 0.0]
    [summary] = fan.rollout_summaries
    assert summary.failed is True
    assert summary.terminal_metrics.failed_month_index == 0
    assert summary.terminal_metrics.cash_usd == 0.0
    assert summary.terminal_metrics.holding_value_usd == 0.0
    assert summary.terminal_metrics.net_worth_usd == 0.0
    assert summary.terminal_metrics.shortfall_usd == 300_000.0

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert detail.rollout.failed is True
    assert detail.rollout.monthly_metrics["cash_usd"] == [250_000.0, 0.0, 0.0, 0.0]
    assert detail.rollout.monthly_metrics["holding_value_usd"] == [750_000.0, 0.0, 0.0, 0.0]
    assert detail.rollout.monthly_metrics["net_worth_usd"] == [1_025_000.0, 0.0, 0.0, 0.0]
    assert [event.kind for event in detail.rollout.events] == ["monthly_expense", "failure"]
    expense, failure = detail.rollout.events
    assert isinstance(expense, MonthlyExpenseEvent)
    assert isinstance(failure, RolloutFailureEvent)
    assert expense.amount_paid_usd == 0.0
    assert expense.shortfall_usd == 300_000.0
    assert failure.shortfall_usd == 300_000.0


def test_default_funding_policy_sells_holdings_for_required_spend(
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
    holding_value_usd = columns["holding_value_usd"]
    assert holding_value_usd[0] == 750_000.0
    terminal_holding_value_usd = float(holding_value_usd[1])  # type: ignore[arg-type]
    assert 0.0 < terminal_holding_value_usd < 750_000.0
    assert detail.rollout.terminal_metrics.cash_usd == 0.0
    assert detail.rollout.terminal_metrics.shortfall_usd == 0.0
    terminal_pe_value_usd = float(columns["private_equity_value_usd"][1])  # type: ignore[arg-type]
    assert detail.rollout.terminal_metrics.net_worth_usd == pytest.approx(
        terminal_holding_value_usd + terminal_pe_value_usd
    )
    assert [event.kind for event in detail.rollout.events] == ["holding_sale", "monthly_expense"]
    sale, expense = detail.rollout.events
    assert isinstance(sale, HoldingSaleEvent)
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
    assert [event.kind for event in detail.rollout.events] == ["holding_sale", "monthly_expense"]
    sale, expense = detail.rollout.events
    assert isinstance(sale, HoldingSaleEvent)
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


def test_product_rollout_includes_federal_and_california_tax_events_for_holding_sales(
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


def _mortgage_purchase_scenario() -> ScenarioKey:
    return ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=2,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property",
            financing=MortgageFinancing(term_months=360, down_payment_pct=20.0, annual_rate_pct=7.0),
            is_primary_residence=True,
        ),
    )


def test_property_purchase_emits_purchase_mortgage_and_property_tax_events(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)

    detail = product.rollout(RolloutRequest(scenario=_mortgage_purchase_scenario(), seed=7))

    [purchase] = [event for event in detail.rollout.events if event.kind == "property_purchase"]
    assert isinstance(purchase, PropertyPurchaseEvent)
    assert purchase.property_id == "location_a_property"
    assert purchase.month_index == 0
    assert purchase.purchase_price_usd == pytest.approx(900_000.0)
    assert purchase.down_payment_usd == pytest.approx(180_000.0)
    assert purchase.mortgage_principal_usd == pytest.approx(720_000.0)

    [closing] = [event for event in detail.rollout.events if event.kind == "closing_cost_payment"]
    assert isinstance(closing, ClosingCostPaymentEvent)
    assert closing.property_id == "location_a_property"
    assert closing.month_index == 0
    assert closing.amount_usd == pytest.approx(900_000.0 * 0.015)

    mortgage_payments = [event for event in detail.rollout.events if event.kind == "mortgage_payment"]
    monthly_payment = 720_000.0 * (0.07 / 12) / (1.0 - (1.0 + 0.07 / 12) ** -360)
    assert mortgage_payments
    for event in mortgage_payments:
        assert isinstance(event, MortgagePaymentEvent)
        assert event.amount_usd == pytest.approx(monthly_payment)
        assert event.interest_usd + event.principal_usd == pytest.approx(monthly_payment)

    property_taxes = [event for event in detail.rollout.events if event.kind == "property_tax_payment"]
    monthly_property_tax = 900_000.0 * 0.01 / 12.0
    assert property_taxes
    for tax_event in property_taxes:
        assert isinstance(tax_event, PropertyTaxPaymentEvent)
        assert tax_event.amount_due_usd == pytest.approx(monthly_property_tax)
        assert tax_event.amount_paid_usd == pytest.approx(monthly_property_tax)
        assert tax_event.shortfall_usd == 0.0


def test_property_purchase_metrics_track_value_balance_and_equity(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)

    detail = product.rollout(RolloutRequest(scenario=_mortgage_purchase_scenario(), seed=7))

    # month_index=0 is the pre-purchase opening snapshot; the property activates at index 1
    # (end of purchase month). Values mark-to-market against the home_value series so the index-1
    # value may deviate from the $900k purchase price, but it must be positive and obey the
    # accounting identities below.
    metrics = detail.rollout.monthly_metrics
    assert float(metrics["property_value_usd"][0]) == 0.0  # type: ignore[arg-type]
    assert float(metrics["mortgage_balance_usd"][0]) == 0.0  # type: ignore[arg-type]
    property_value_usd = float(metrics["property_value_usd"][1])  # type: ignore[arg-type]
    mortgage_balance_usd = float(metrics["mortgage_balance_usd"][1])  # type: ignore[arg-type]
    home_equity_usd = float(metrics["home_equity_usd"][1])  # type: ignore[arg-type]
    liquid_net_worth_usd = float(metrics["liquid_net_worth_usd"][1])  # type: ignore[arg-type]
    private_equity_value_usd = float(metrics["private_equity_value_usd"][1])  # type: ignore[arg-type]
    net_worth_usd = float(metrics["net_worth_usd"][1])  # type: ignore[arg-type]

    assert property_value_usd > 0.0
    assert mortgage_balance_usd == pytest.approx(720_000.0)
    assert home_equity_usd == pytest.approx(property_value_usd - mortgage_balance_usd)
    assert net_worth_usd == pytest.approx(liquid_net_worth_usd + home_equity_usd + private_equity_value_usd)
    # Required-level-series should include the location's home-value series.
    assert "home_value:location_a" in counting_exogenous_model.sample_requests[0].required_level_series


def test_cash_property_purchase_omits_mortgage_payments(counting_exogenous_model: CountingExogenousModel) -> None:
    augur_config = _augur_config()
    augur_config = augur_config.model_copy(
        update={"snapshot": augur_config.snapshot.model_copy(update={"cash_usd": 1_200_000.0})}
    )
    product = _service(counting_exogenous_model, augur_config=augur_config)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=2,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property", financing=CashFinancing(), is_primary_residence=True
        ),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    [purchase] = [event for event in detail.rollout.events if event.kind == "property_purchase"]
    assert isinstance(purchase, PropertyPurchaseEvent)
    assert purchase.down_payment_usd == pytest.approx(900_000.0)
    assert purchase.mortgage_principal_usd == 0.0
    [closing] = [event for event in detail.rollout.events if event.kind == "closing_cost_payment"]
    assert isinstance(closing, ClosingCostPaymentEvent)
    assert closing.amount_usd == pytest.approx(900_000.0 * 0.015)
    assert [event for event in detail.rollout.events if event.kind == "mortgage_payment"] == []
    assert detail.rollout.monthly_metrics["mortgage_balance_usd"][0] == 0.0


def test_property_purchase_emits_hoa_dues_when_property_has_monthly_hoa(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    # location_b_property has hoa_monthly_usd=150 in the public fixture.
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=3,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_b_property",
            financing=MortgageFinancing(term_months=360, down_payment_pct=20.0, annual_rate_pct=7.0),
            is_primary_residence=True,
        ),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    hoa_events = [event for event in detail.rollout.events if event.kind == "hoa_dues_payment"]
    assert hoa_events
    for event in hoa_events:
        assert isinstance(event, HoaDuesPaymentEvent)
        # Base is 150.0 USD/month; inflation-indexed so the realized amount drifts each month, but it
        # must stay near base on a short horizon.
        assert event.amount_due_usd == pytest.approx(150.0, rel=0.1)
        assert event.amount_paid_usd == pytest.approx(event.amount_due_usd)
        assert event.shortfall_usd == 0.0
    assert INFLATION_SERIES_ID in counting_exogenous_model.sample_requests[0].required_level_series


def test_property_purchase_skips_hoa_when_property_has_no_monthly_hoa(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    # location_a_property has hoa_monthly_usd=0 in the public fixture.
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=3,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property",
            financing=MortgageFinancing(term_months=360, down_payment_pct=20.0, annual_rate_pct=7.0),
            is_primary_residence=True,
        ),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert [event for event in detail.rollout.events if event.kind == "hoa_dues_payment"] == []


def test_property_purchase_emits_homeowners_insurance_at_default_pct(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    # location_a_property is $900k. Default annual_insurance_pct=0.4 → $300/mo at month 0.
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=3,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property",
            financing=MortgageFinancing(term_months=360, down_payment_pct=20.0, annual_rate_pct=7.0),
            is_primary_residence=True,
        ),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    insurance_events = [event for event in detail.rollout.events if event.kind == "homeowners_insurance_payment"]
    assert insurance_events
    monthly_premium = 0.4 / 100.0 * 900_000.0 / 12.0
    for event in insurance_events:
        assert isinstance(event, HomeownersInsurancePaymentEvent)
        assert event.amount_due_usd == pytest.approx(monthly_premium, rel=0.1)
        assert event.amount_paid_usd == pytest.approx(event.amount_due_usd)
        assert event.shortfall_usd == 0.0


def test_property_purchase_with_zero_insurance_pct_omits_insurance(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=2,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property", financing=CashFinancing(), is_primary_residence=True
        ),
        annual_insurance_pct=0.0,
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert [event for event in detail.rollout.events if event.kind == "homeowners_insurance_payment"] == []


def test_property_purchase_emits_maintenance_at_default_pct(counting_exogenous_model: CountingExogenousModel) -> None:
    product = _service(counting_exogenous_model)
    # location_a_property is $900k. Default annual_maintenance_pct=1.0 → $750/mo at month 0.
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=3,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property",
            financing=MortgageFinancing(term_months=360, down_payment_pct=20.0, annual_rate_pct=7.0),
            is_primary_residence=True,
        ),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    maintenance_events = [event for event in detail.rollout.events if event.kind == "property_maintenance_payment"]
    assert maintenance_events
    monthly_amount = 1.0 / 100.0 * 900_000.0 / 12.0
    for event in maintenance_events:
        assert isinstance(event, PropertyMaintenancePaymentEvent)
        assert event.amount_due_usd == pytest.approx(monthly_amount, rel=0.1)
        assert event.amount_paid_usd == pytest.approx(event.amount_due_usd)
        assert event.shortfall_usd == 0.0


def test_property_purchase_with_zero_maintenance_pct_omits_maintenance(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=2,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property", financing=CashFinancing(), is_primary_residence=True
        ),
        annual_maintenance_pct=0.0,
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert [event for event in detail.rollout.events if event.kind == "property_maintenance_payment"] == []


def test_property_purchase_rejects_unknown_property(counting_exogenous_model: CountingExogenousModel) -> None:
    product = _service(counting_exogenous_model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=2,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        property_purchase=PropertyPurchase(
            property_id="ghost_property", financing=CashFinancing(), is_primary_residence=True
        ),
    )

    with pytest.raises(ValueError, match=r"unknown property_id"):
        product.rollout(RolloutRequest(scenario=scenario, seed=7))


def test_primary_residence_mortgage_emits_mortgage_interest_deduction_policy(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    """A mortgaged primary residence builds one MortgageInterestDeductionPolicy on the sim
    Scenario; tax_accrual events surface a non-zero mortgage_interest_deduction_usd."""
    augur_config = _augur_config()
    augur_config = augur_config.model_copy(
        update={"snapshot": augur_config.snapshot.model_copy(update={"cash_usd": 400_000.0})}
    )
    product = _service(counting_exogenous_model, augur_config=augur_config)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=13,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property",
            financing=MortgageFinancing(term_months=360, down_payment_pct=20.0, annual_rate_pct=7.0),
            is_primary_residence=True,
        ),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    accruals = [event for event in detail.rollout.events if event.kind == "tax_accrual"]
    federal_accrual = one(event for event in accruals if event.jurisdiction_id == "federal_us")
    assert federal_accrual.mortgage_interest_deduction_usd > 0.0
    assert federal_accrual.standard_deduction_usd == pytest.approx(14_600.0)
    # MID on a $900k * 80% = $720k mortgage is comfortably above the standard deduction.
    assert federal_accrual.itemized_deduction_usd > federal_accrual.standard_deduction_usd


def test_secondary_residence_mortgage_omits_mortgage_interest_deduction(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    """`is_primary_residence=False` should produce zero MID even with a mortgage."""
    augur_config = _augur_config()
    augur_config = augur_config.model_copy(
        update={"snapshot": augur_config.snapshot.model_copy(update={"cash_usd": 400_000.0})}
    )
    product = _service(counting_exogenous_model, augur_config=augur_config)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=13,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property",
            financing=MortgageFinancing(term_months=360, down_payment_pct=20.0, annual_rate_pct=7.0),
            is_primary_residence=False,
        ),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    federal_accrual = one(
        event
        for event in detail.rollout.events
        if event.kind == "tax_accrual" and event.jurisdiction_id == "federal_us"
    )
    assert federal_accrual.mortgage_interest_deduction_usd == 0.0
    assert federal_accrual.itemized_deduction_usd == 0.0
    assert federal_accrual.standard_deduction_usd == pytest.approx(14_600.0)


def test_cash_property_purchase_omits_mortgage_interest_deduction(
    counting_exogenous_model: CountingExogenousModel,
) -> None:
    """A cash purchase has no mortgage and therefore no MID even when is_primary_residence=True."""
    augur_config = _augur_config()
    augur_config = augur_config.model_copy(
        update={"snapshot": augur_config.snapshot.model_copy(update={"cash_usd": 1_200_000.0})}
    )
    product = _service(counting_exogenous_model, augur_config=augur_config)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model",
        horizon_months=13,
        monthly_spend_usd=1_000.0,
        spend_index="none",
        funding_policy=FundingPolicy(sell_order=()),
        property_purchase=PropertyPurchase(
            property_id="location_a_property", financing=CashFinancing(), is_primary_residence=True
        ),
    )

    detail = product.rollout(RolloutRequest(scenario=scenario, seed=7))

    federal_accrual = one(
        event
        for event in detail.rollout.events
        if event.kind == "tax_accrual" and event.jurisdiction_id == "federal_us"
    )
    assert federal_accrual.mortgage_interest_deduction_usd == 0.0
    assert federal_accrual.itemized_deduction_usd == 0.0


if __name__ == "__main__":
    pytest_bazel.main()
