from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import polars as pl
import pytest
import pytest_bazel

from finance.augur.model.series import SecurityKey, SecuritySymbol
from finance.augur.sim.locations import Location
from finance.augur.sim.projections import project_simulation_run
from finance.augur.sim.scenario import (
    ORDINARY_INCOME,
    Agent,
    FilingStatus,
    InitialAccountBalance,
    InitialLot,
    MortgageFinancing,
    PropertyTaxPolicy,
    RecurringTransfer,
    Scenario,
    ScheduledAssetSale,
    ScheduledObligation,
    ScheduledPropertyPurchase,
    SleeveTarget,
    TargetAllocationPolicy,
    TaxProfile,
)
from finance.augur.sim.simulate import simulate


def _quanta(amount: float | int) -> int:
    return int((Decimal(str(amount)) / Decimal("0.01")).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def test_projection_due_now_obligation_sells_assets_and_settles(deterministic_series_bundle) -> None:
    scenario = Scenario(
        agents=[Agent(agent_id="alice"), Agent(agent_id="landlord")],
        initial_cash=[
            InitialAccountBalance(agent_id="alice", account_id="checking", balance=100),
            InitialAccountBalance(agent_id="landlord", account_id="checking", balance=0),
        ],
        initial_lots=[
            InitialLot(
                lot_id="alice_vti",
                agent_id="alice",
                asset=SecurityKey(symbol=SecuritySymbol("vti")),
                purchase_month_index=-24,
                quantity=10.0,
                cost_basis_per_unit=50,
            )
        ],
        scheduled_obligations=[
            ScheduledObligation(
                month=0,
                obligation_id="rent_due",
                obligation_type="rent",
                agent_id="alice",
                from_account_id="checking",
                to_agent_id="landlord",
                to_account_id="checking",
                amount_due=500,
            )
        ],
        external_series=deterministic_series_bundle([100.0, 100.0]),
        target_allocation_policies=[
            TargetAllocationPolicy(
                agent_id="alice",
                account_id="checking",
                sleeves=[SleeveTarget(asset=SecurityKey(symbol=SecuritySymbol("vti")), weight=1)],
                cash_ceiling=0,
            )
        ],
        tax_profiles=[],
        horizon_months=1,
    )

    projection = project_simulation_run(simulate(scenario, rollout_count=1, locations={}))

    lifecycle = projection.obligation_lifecycle.row(0, named=True)
    assert lifecycle["obligation_id"] == "rent_due_m0"
    assert lifecycle["status"] == "paid"
    assert lifecycle["amount_due_quanta"] == _quanta(500)
    assert lifecycle["amount_paid_quanta"] == _quanta(500)
    assert lifecycle["shortfall_quanta"] == 0
    assert lifecycle["attempted_funding_sources"] == "security:vti"

    alice_final = _net_worth_row(projection.net_worth, agent_id="alice", month=1)
    assert alice_final["cash_quanta"] == 0
    assert alice_final["liquid_asset_value_quanta"] == _quanta(600)
    assert alice_final["asset_book_value_quanta"] == _quanta(300)
    assert alice_final["liquid_net_worth_quanta"] == _quanta(600)
    assert alice_final["book_net_worth_quanta"] == _quanta(300)

    transaction_types = set(projection.transactions.get_column("transaction_type").to_list())
    assert {"asset_sale", "cash_transfer", "obligation_settlement"} <= transaction_types
    sale = projection.transactions.filter(pl.col("transaction_type") == "asset_sale").row(0, named=True)
    assert sale["transaction_id"] == "allocation_sale_m0_security:vti:alice_vti"
    assert sale["amount_quanta"] == _quanta(400)
    assert sale["quantity"] == pytest.approx(4.0)

    summary = projection.rollout_summary.row(0, named=True)
    assert summary["status"] == "active"
    assert summary["failure_count"] == 0


def test_projection_due_now_obligation_failure_is_explicit() -> None:
    scenario = Scenario(
        agents=[Agent(agent_id="alice"), Agent(agent_id="landlord")],
        initial_cash=[
            InitialAccountBalance(agent_id="alice", account_id="checking", balance=100),
            InitialAccountBalance(agent_id="landlord", account_id="checking", balance=0),
        ],
        scheduled_obligations=[
            ScheduledObligation(
                month=0,
                obligation_id="rent_due",
                obligation_type="rent",
                agent_id="alice",
                from_account_id="checking",
                to_agent_id="landlord",
                to_account_id="checking",
                amount_due=500,
            )
        ],
        tax_profiles=[],
        horizon_months=1,
    )

    projection = project_simulation_run(simulate(scenario, rollout_count=1, locations={}))

    lifecycle = projection.obligation_lifecycle.row(0, named=True)
    assert lifecycle["status"] == "failed"
    assert lifecycle["amount_paid_quanta"] == 0
    assert lifecycle["shortfall_quanta"] == _quanta(500)
    assert set(projection.transactions.get_column("transaction_type").to_list()) == {"obligation_settlement"}
    assert projection.transactions.get_column("amount_quanta").to_list() == [0]

    failure = projection.failures.row(0, named=True)
    assert failure["failure_id"] == "rent_due_m0_failure"
    assert failure["obligation_id"] == "rent_due_m0"
    assert failure["obligation_type"] == "rent"
    assert failure["shortfall_quanta"] == _quanta(500)

    summary = projection.rollout_summary.row(0, named=True)
    assert summary["status"] == "failed_insufficient_cash"
    assert summary["failed_month"] == 0
    assert summary["failure_count"] == 1
    assert summary["first_failure_month"] == 0


def test_projection_tax_safe_harbor_breakdown_and_payments() -> None:
    scenario = Scenario(
        agents=[Agent(agent_id="alice"), Agent(agent_id="payroll"), Agent(agent_id="irs")],
        initial_cash=[
            InitialAccountBalance(agent_id="alice", account_id="checking", balance=1000),
            InitialAccountBalance(agent_id="payroll", account_id="checking", balance=0),
            InitialAccountBalance(agent_id="irs", account_id="checking", balance=0),
        ],
        initial_lots=[
            InitialLot(
                lot_id="alice_long_vti",
                agent_id="alice",
                asset=SecurityKey(symbol=SecuritySymbol("vti")),
                purchase_month_index=-24,
                quantity=100.0,
                cost_basis_per_unit=80,
            )
        ],
        recurring_transfers=[
            RecurringTransfer(
                start_month=0,
                end_month=11,
                cause_id="alice_paycheck",
                from_agent_id="payroll",
                from_account_id="checking",
                to_agent_id="alice",
                to_account_id="checking",
                amount=(Decimal(50000) / Decimal(12)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                income_category=ORDINARY_INCOME,
            )
        ],
        scheduled_asset_sales=[
            ScheduledAssetSale(
                month=6,
                cause_id="alice_long_sale",
                agent_id="alice",
                asset=SecurityKey(symbol=SecuritySymbol("vti")),
                quantity=100.0,
                price_per_unit=280,
                proceeds_account_id="checking",
            )
        ],
        tax_profiles=[
            TaxProfile(
                agent_id="alice",
                filing_status=FilingStatus.SINGLE,
                jurisdiction_ids=["federal_us", "california"],
                tax_authority_agent_id="irs",
                prior_year_tax=4000,
            )
        ],
        horizon_months=13,
    )

    projection = project_simulation_run(simulate(scenario, rollout_count=1, locations={}))

    breakdowns = {
        row["jurisdiction_id"]: row for row in projection.tax_breakdowns.sort("jurisdiction_id").iter_rows(named=True)
    }
    assert breakdowns["federal_us"]["tax_year"] == 0
    assert breakdowns["federal_us"]["ordinary_taxable_quanta"] == _quanta(35_400.04)
    assert breakdowns["federal_us"]["capital_gain_taxable_quanta"] == _quanta(20_000)
    assert breakdowns["federal_us"]["ordinary_tax_quanta"] == _quanta(4_016)
    assert breakdowns["federal_us"]["capital_gain_tax_quanta"] == _quanta(1_256.26)
    assert breakdowns["california"]["total_tax_quanta"] == _quanta(2_712.36)

    paid_tax_obligations = projection.obligation_lifecycle.filter(
        pl.col("obligation_type").is_in(["estimated_tax", "tax_true_up"])
    ).sort(["month_index", "obligation_id"])
    assert paid_tax_obligations.select("month_index", "obligation_id", "amount_paid_quanta", "status").to_dicts() == [
        {
            "month_index": 3,
            "obligation_id": "alice_estimated_tax_q1_y0",
            "amount_paid_quanta": _quanta(1_000),
            "status": "paid",
        },
        {
            "month_index": 5,
            "obligation_id": "alice_estimated_tax_q2_y0",
            "amount_paid_quanta": _quanta(1_000),
            "status": "paid",
        },
        {
            "month_index": 8,
            "obligation_id": "alice_estimated_tax_q3_y0",
            "amount_paid_quanta": _quanta(1_000),
            "status": "paid",
        },
        {
            "month_index": 12,
            "obligation_id": "alice_estimated_tax_q4_y0",
            "amount_paid_quanta": _quanta(1_000),
            "status": "paid",
        },
        {
            "month_index": 12,
            "obligation_id": "alice_tax_true_up_y0",
            "amount_paid_quanta": pytest.approx(_quanta(3_984.62), abs=2),
            "status": "paid",
        },
    ]

    alice_final = _net_worth_row(projection.net_worth, agent_id="alice", month=13)
    assert alice_final["cash_quanta"] == pytest.approx(_quanta(71_015.42), abs=2)
    assert alice_final["book_net_worth_quanta"] == pytest.approx(_quanta(71_015.42), abs=2)


def test_projection_real_estate_book_net_worth_and_liability_balance(san_francisco_location: Location) -> None:
    scenario = Scenario(
        agents=[
            Agent(agent_id="alice"),
            Agent(agent_id="seller"),
            Agent(agent_id="bank"),
            Agent(agent_id="sf_tax_collector"),
        ],
        initial_cash=[
            InitialAccountBalance(agent_id="alice", account_id="checking", balance=120000),
            InitialAccountBalance(agent_id="seller", account_id="checking", balance=0),
            InitialAccountBalance(agent_id="bank", account_id="checking", balance=0),
            InitialAccountBalance(agent_id="sf_tax_collector", account_id="checking", balance=0),
        ],
        scheduled_property_purchases=[
            ScheduledPropertyPurchase(
                month=0,
                cause_id="alice_buys_sf_home",
                property_id="sf_home",
                location_id="san_francisco",
                buyer_agent_id="alice",
                buyer_account_id="checking",
                seller_agent_id="seller",
                purchase_price=500000,
                down_payment=100000,
                buyer_closing_cost=10000,
                mortgage=MortgageFinancing(
                    liability_id="sf_home_mortgage",
                    lender_agent_id="bank",
                    principal=400000,
                    annual_interest_rate=0.06,
                    term_months=360,
                ),
            )
        ],
        property_tax_policies=[
            PropertyTaxPolicy(
                property_id="sf_home",
                owner_agent_id="alice",
                tax_authority_agent_id="sf_tax_collector",
                annual_tax_rate=0.012,
            )
        ],
        tax_profiles=[],
        horizon_months=2,
    )

    projection = project_simulation_run(
        simulate(scenario, rollout_count=1, locations={"san_francisco": san_francisco_location})
    )

    mortgage_payment = 400_000.0 * 0.005 / (1.0 - (1.005**-360))
    expected_cash = 120_000.0 - 110_000.0 - mortgage_payment - 500.0
    expected_principal = 400_000.0 - (mortgage_payment - 2_000.0)
    alice_final = _net_worth_row(projection.net_worth, agent_id="alice", month=2)
    assert alice_final["cash_quanta"] == pytest.approx(_quanta(expected_cash), abs=1)
    assert alice_final["property_book_value_quanta"] == _quanta(510_000)
    assert alice_final["liability_principal_quanta"] == pytest.approx(_quanta(expected_principal), abs=1)
    assert alice_final["book_net_worth_quanta"] == pytest.approx(
        _quanta(expected_cash + 510_000.0 - expected_principal), abs=1
    )
    assert alice_final["liquid_net_worth_quanta"] == pytest.approx(_quanta(expected_cash), abs=1)

    mortgage_account = projection.account_balances.filter(
        (pl.col("month_index") == 2) & (pl.col("account_id") == "sf_home_mortgage")
    ).row(0, named=True)
    assert mortgage_account["account_type"] == "liability"
    assert mortgage_account["balance_quanta"] == pytest.approx(_quanta(-expected_principal), abs=1)

    obligation_types = set(projection.obligation_lifecycle.get_column("obligation_type").to_list())
    assert {"mortgage_payment", "property_tax"} <= obligation_types
    assert projection.failures.is_empty()


def test_projection_trajectory_filters_one_rollout() -> None:
    scenario = Scenario(
        agents=[Agent(agent_id="alice")],
        initial_cash=[InitialAccountBalance(agent_id="alice", account_id="checking", balance=10)],
        tax_profiles=[],
        horizon_months=1,
    )

    projection = project_simulation_run(simulate(scenario, rollout_count=2, locations={}))
    trajectory = projection.trajectory(1)

    assert set(trajectory.net_worth.get_column("rollout_index").to_list()) == {1}
    assert set(trajectory.account_balances.get_column("rollout_index").to_list()) == {1}
    assert trajectory.rollout_summary.row(0, named=True)["rollout_index"] == 1


def _net_worth_row(frame: pl.DataFrame, *, agent_id: str, month: int) -> dict[str, object]:
    return frame.filter((pl.col("agent_id") == agent_id) & (pl.col("month_index") == month)).row(0, named=True)


if __name__ == "__main__":
    pytest_bazel.main()
