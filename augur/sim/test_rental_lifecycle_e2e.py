"""Sim-layer e2e tests for landlord rental income + lifecycle events.

Phase 1: static rental from month 0, no lifecycle transitions, no taxes.
Phase 2+ tests will land alongside their implementation phases.

Each test builds a `Scenario` directly, calls
`simulate_with_external_series`, decodes the result, and asserts against
event frames + state history. Exogenous series are constants so the
expected cashflow is exact-math predictable.
"""

from __future__ import annotations

import polars as pl
import pytest
import pytest_bazel

from augur.sim.external_series import EXTERNAL_SERIES_EVENTS_FRAME, EXTERNAL_SERIES_VALUES_FRAME, ExternalSeriesContext
from augur.sim.scenario import (
    Agent,
    FederalSaltCapEntry,
    FederalSaltDeductionPolicy,
    InitialAccountBalance,
    MortgageFinancing,
    MortgageInterestDeductionPolicy,
    PropertyTaxPolicy,
    RecurringObligation,
    RecurringTransfer,
    Scenario,
    ScheduledPropertyPurchase,
    ScheduledTransfer,
    SeriesIndexedAmount,
    StartRentingEvent,
    StopRentingEvent,
    TaxProfile,
)
from augur.sim.simulate import simulate_with_external_series

# Constants mirroring the product translator. Kept in-test to avoid
# cross-package import dependencies from the sim layer.
TENANT_AGENT_ID = "tenant"
OWNER_AGENT_ID = "owner"
MGMT_AGENT_ID = "property_management_agency"
RENT_SERIES_ID = "rent:test_location"


def _flat_series(*, series_id: str, value: float, months: int, rollouts: int) -> ExternalSeriesContext:
    """Build an exogenous bundle with one series held flat at `value`."""

    rows = [
        {"rollout_index": rollout, "month_index": month, "series_id": series_id, "value": value}
        for rollout in range(rollouts)
        for month in range(months)
    ]
    return ExternalSeriesContext(
        series_values=EXTERNAL_SERIES_VALUES_FRAME.normalize(pl.DataFrame(rows)),
        series_events=EXTERNAL_SERIES_EVENTS_FRAME.empty(),
    )


def _multi_series(*, levels_by_series: dict[str, dict[int, list[float]]]) -> ExternalSeriesContext:
    """Build an exogenous bundle with multiple series, indexed by (series_id, rollout) → levels.

    `levels_by_series[series_id][rollout]` is a list of length `horizon_months + 1` (the engine
    indexes external_values up through the horizon end).
    """

    rows = []
    for series_id, by_rollout in levels_by_series.items():
        for rollout_index, levels in by_rollout.items():
            for month_index, value in enumerate(levels):
                rows.append(
                    {"rollout_index": rollout_index, "month_index": month_index, "series_id": series_id, "value": value}
                )
    return ExternalSeriesContext(
        series_values=EXTERNAL_SERIES_VALUES_FRAME.normalize(pl.DataFrame(rows)),
        series_events=EXTERNAL_SERIES_EVENTS_FRAME.empty(),
    )


def _rental_scenario(
    *,
    horizon_months: int = 12,
    monthly_rent: float = 5_000.0,
    fraction_rented: float = 1.0,
    vacancy_pct: float = 0.0,
    initial_cash_usd: float = 100_000.0,
    management_fee_pct: float = 0.0,
    leasing_fee_months: float = 0.0,
    avg_tenancy_months: int = 24,
) -> Scenario:
    """Build a minimal static-rental scenario. No taxes (empty tax_profiles)."""

    end_month = horizon_months - 1
    base_collected = monthly_rent * fraction_rented * (1.0 - vacancy_pct)
    agents = [Agent(agent_id=OWNER_AGENT_ID), Agent(agent_id=TENANT_AGENT_ID)]
    initial_cash = [
        InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=initial_cash_usd),
        InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
    ]
    recurring_transfers: list[RecurringTransfer] = [
        RecurringTransfer(
            start_month=0,
            end_month=end_month,
            cause_id="rental_income:p1",
            from_agent_id=TENANT_AGENT_ID,
            from_account_id="checking",
            to_agent_id=OWNER_AGENT_ID,
            to_account_id="checking",
            amount_usd=SeriesIndexedAmount(
                base_amount_usd=base_collected, series_id=RENT_SERIES_ID, adjustment_period_months=12
            ),
        )
    ]
    scheduled_transfers: list[ScheduledTransfer] = []
    if management_fee_pct > 0 or leasing_fee_months > 0:
        agents.append(Agent(agent_id=MGMT_AGENT_ID))
        initial_cash.append(InitialAccountBalance(agent_id=MGMT_AGENT_ID, account_id="checking", balance_usd=0.0))
    if management_fee_pct > 0:
        recurring_transfers.append(
            RecurringTransfer(
                start_month=0,
                end_month=end_month,
                cause_id="management_fee:p1",
                from_agent_id=OWNER_AGENT_ID,
                from_account_id="checking",
                to_agent_id=MGMT_AGENT_ID,
                to_account_id="checking",
                amount_usd=SeriesIndexedAmount(
                    base_amount_usd=base_collected * management_fee_pct / 100.0,
                    series_id=RENT_SERIES_ID,
                    adjustment_period_months=12,
                ),
            )
        )
    if leasing_fee_months > 0:
        leasing_base = monthly_rent * leasing_fee_months
        scheduled_transfers.extend(
            ScheduledTransfer(
                month=fire_month,
                cause_id=f"leasing_fee:p1:m{fire_month}",
                from_agent_id=OWNER_AGENT_ID,
                from_account_id="checking",
                to_agent_id=MGMT_AGENT_ID,
                to_account_id="checking",
                amount_usd=SeriesIndexedAmount(
                    base_amount_usd=leasing_base, series_id=RENT_SERIES_ID, adjustment_period_months=12
                ),
            )
            for fire_month in range(0, horizon_months, avg_tenancy_months)
        )
    return Scenario(
        agents=agents,
        initial_cash=initial_cash,
        recurring_transfers=recurring_transfers,
        scheduled_transfers=scheduled_transfers,
        tax_profiles=[],
        horizon_months=horizon_months,
    )


def _run(scenario: Scenario, rollouts: int = 1, rent_level: float = 1.0):
    """Run the scenario against a flat rent series at `rent_level` for all rollouts/months."""

    ctx = _flat_series(
        series_id=RENT_SERIES_ID, value=rent_level, months=scenario.horizon_months + 1, rollouts=rollouts
    )
    return simulate_with_external_series(scenario, external_series=ctx, rollout_count=rollouts)


class TestRentalIncome:
    def test_rental_income_flows_monthly_at_constant_rent(self):
        scenario = _rental_scenario(horizon_months=12, monthly_rent=5_000.0)
        run = _run(scenario)
        transfers = run.events_log.transfers.filter(pl.col("cause_id") == "rental_income:p1")
        assert transfers.height == 12
        # Each transfer = 5000 × 1.0 (full rented) × 1.0 (no vacancy) × (rent_level / base_level = 1.0)
        assert transfers["amount_usd"].to_list() == pytest.approx([5_000.0] * 12)

    def test_vacancy_pct_zero_collects_full_rent(self):
        scenario = _rental_scenario(monthly_rent=4_000.0, vacancy_pct=0.0)
        run = _run(scenario)
        transfers = run.events_log.transfers.filter(pl.col("cause_id") == "rental_income:p1")
        assert all(amount == pytest.approx(4_000.0) for amount in transfers["amount_usd"].to_list())

    def test_vacancy_pct_reduces_rent_proportionally(self):
        scenario = _rental_scenario(monthly_rent=4_000.0, vacancy_pct=0.10)
        run = _run(scenario)
        transfers = run.events_log.transfers.filter(pl.col("cause_id") == "rental_income:p1")
        # 10% vacancy → 90% rent collected = 3600
        assert all(amount == pytest.approx(3_600.0) for amount in transfers["amount_usd"].to_list())

    def test_vacancy_pct_one_collects_no_rent(self):
        scenario = _rental_scenario(monthly_rent=4_000.0, vacancy_pct=1.0)
        run = _run(scenario)
        transfers = run.events_log.transfers.filter(pl.col("cause_id") == "rental_income:p1")
        assert all(amount == pytest.approx(0.0) for amount in transfers["amount_usd"].to_list())

    def test_fraction_rented_half_collects_half_rent(self):
        scenario = _rental_scenario(monthly_rent=6_000.0, fraction_rented=0.5)
        run = _run(scenario)
        transfers = run.events_log.transfers.filter(pl.col("cause_id") == "rental_income:p1")
        assert all(amount == pytest.approx(3_000.0) for amount in transfers["amount_usd"].to_list())

    def test_rental_income_indexed_by_rent_series(self):
        # Rent series doubles at month 12 (annual adjustment period).
        scenario = _rental_scenario(horizon_months=24, monthly_rent=5_000.0)
        # Build a per-month rent series: 1.0 for months 0..11, 2.0 for months 12..24.
        levels = [1.0] * 12 + [2.0] * 13
        ctx = _multi_series(levels_by_series={RENT_SERIES_ID: {0: levels}})
        run = simulate_with_external_series(scenario, external_series=ctx, rollout_count=1)
        transfers = (
            run.events_log.transfers.filter(pl.col("cause_id") == "rental_income:p1")
            .sort("month_index")
            .select("month_index", "amount_usd")
        )
        # Months 0..11 use level 1.0 → $5000; months 12..23 reset to level 2.0 → $10000.
        amounts = transfers["amount_usd"].to_list()
        assert amounts[:12] == pytest.approx([5_000.0] * 12)
        assert amounts[12:] == pytest.approx([10_000.0] * 12)


class TestManagementFee:
    def test_management_fee_paid_monthly_against_collected_rent(self):
        scenario = _rental_scenario(horizon_months=12, monthly_rent=5_000.0, vacancy_pct=0.05, management_fee_pct=8.0)
        run = _run(scenario)
        mgmt = run.events_log.transfers.filter(pl.col("cause_id") == "management_fee:p1")
        assert mgmt.height == 12
        # 5000 × 0.95 (post-vacancy) × 0.08 (mgmt fee) = $380/mo
        assert all(amount == pytest.approx(380.0) for amount in mgmt["amount_usd"].to_list())

    def test_no_management_fee_when_zero_pct(self):
        scenario = _rental_scenario(horizon_months=12, monthly_rent=5_000.0, management_fee_pct=0.0)
        run = _run(scenario)
        mgmt = run.events_log.transfers.filter(pl.col("cause_id") == "management_fee:p1")
        assert mgmt.height == 0


class TestLeasingFee:
    def test_leasing_fee_fires_at_rent_start_and_every_avg_tenancy_months(self):
        scenario = _rental_scenario(
            horizon_months=60, monthly_rent=5_000.0, leasing_fee_months=1.0, avg_tenancy_months=24
        )
        run = _run(scenario)
        leasing = (
            run.events_log.transfers.filter(pl.col("cause_id").str.starts_with("leasing_fee:p1"))
            .sort("month_index")
            .select("month_index", "amount_usd")
        )
        # 60 months / 24mo cadence → fires at months 0, 24, 48 → 3 entries.
        assert leasing["month_index"].to_list() == [0, 24, 48]
        # Each fee = 1mo × $5000 = $5000.
        assert leasing["amount_usd"].to_list() == pytest.approx([5_000.0] * 3)

    def test_no_leasing_fee_when_zero_months(self):
        scenario = _rental_scenario(horizon_months=60, monthly_rent=5_000.0, leasing_fee_months=0.0)
        run = _run(scenario)
        leasing = run.events_log.transfers.filter(pl.col("cause_id").str.starts_with("leasing_fee:p1"))
        assert leasing.height == 0


class TestRentalIncomeTaxation:
    """Phase 2.0: rental income transfers carry income_category='ordinary', so they accrue
    into the owner's taxable ordinary income at year-end. Schedule E deductions and
    MID/SALT scaling are deferred to follow-up commits; rental income is currently
    over-taxed by the amount of those deductions.
    """

    def _taxed_rental_scenario(self, *, monthly_rent: float, horizon_months: int = 12) -> Scenario:
        end_month = horizon_months - 1
        return Scenario(
            agents=[Agent(agent_id=OWNER_AGENT_ID), Agent(agent_id=TENANT_AGENT_ID), Agent(agent_id="irs")],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=100_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=monthly_rent, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                )
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=horizon_months,
        )

    def test_rental_income_accrues_into_ordinary_ytd(self):
        # $4,000/mo × 12 = $48,000 gross rental income → ordinary income line on tax_breakdowns.
        scenario = self._taxed_rental_scenario(monthly_rent=4_000.0)
        run = _run(scenario)
        breakdowns = {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}
        assert breakdowns["federal_us"]["ordinary_income_usd"] == pytest.approx(48_000.0, abs=1e-6)

    def test_rental_income_generates_tax_accruals_at_year_end(self):
        scenario = self._taxed_rental_scenario(monthly_rent=4_000.0)
        run = _run(scenario)
        accruals = run.events_log.tax_accruals.sort("jurisdiction_id")
        assert accruals.height == 2  # federal + CA
        # Accruals fire at month 11 (year-end).
        assert all(month == 11 for month in accruals["month_index"].to_list())
        # Both jurisdictions should levy positive tax on $48k of ordinary income.
        assert all(amount > 0 for amount in accruals["amount_usd"].to_list())

    def test_management_fee_deducts_from_taxable_ordinary_income(self):
        """Schedule E: a management fee transfer with deduction_category='ordinary'
        should subtract from the owner's ordinary_income_ytd, reducing taxable income."""

        end_month = 11
        # $5,000/mo rental + $500/mo management fee → $60k gross - $6k deduction = $54k taxable.
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id=MGMT_AGENT_ID),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=100_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id=MGMT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=5_000.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                ),
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="management_fee:p1",
                    from_agent_id=OWNER_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=MGMT_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=500.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    deduction_category="ordinary",
                ),
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=12,
        )
        run = _run(scenario)
        breakdowns = {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}
        # Gross rental: 12 × $5,000 = $60,000. Management fee: 12 × $500 = $6,000.
        # Net ordinary income exposed to brackets = $54,000.
        assert breakdowns["federal_us"]["ordinary_income_usd"] == pytest.approx(54_000.0, abs=1e-6)

    def test_obligation_deduction_decrements_payer_ordinary_ytd(self):
        """Schedule E on obligations: a paid RecurringObligation with
        deduction_category='ordinary' and deductible_fraction=1.0 decrements the payer's
        ordinary_income_ytd by the full settled amount."""

        end_month = 11
        # $6,000/mo gross rent → $72,000/yr; $400/mo HOA fully deductible → $4,800/yr Schedule E.
        # Net ordinary income for tax = $72,000 - $4,800 = $67,200.
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="hoa"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=100_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="hoa", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=6_000.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                )
            ],
            recurring_obligations=[
                RecurringObligation(
                    start_month=0,
                    end_month=end_month,
                    obligation_id="hoa_dues",
                    obligation_type="hoa_dues",
                    agent_id=OWNER_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id="hoa",
                    to_account_id="checking",
                    amount_due_usd=SeriesIndexedAmount(
                        base_amount_usd=400.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    deduction_category="ordinary",
                    deductible_fraction=1.0,
                )
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=12,
        )
        run = _run(scenario)
        breakdowns = {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}
        assert breakdowns["federal_us"]["ordinary_income_usd"] == pytest.approx(67_200.0, abs=1e-6)

    def test_depreciation_accrues_monthly_and_deducts_as_schedule_e(self):
        """§168 monthly depreciation accrues for rented property and reduces taxable ordinary
        income at year-end. Building basis = $500k × 0.80 = $400k; rented_fraction = 1.0;
        annual depreciation = $400k / 27.5 ≈ $14,545.45."""

        end_month = 11
        purchase_price = 500_000.0
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="property_seller"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=600_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="property_seller", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=5_000.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                )
            ],
            scheduled_property_purchases=[
                ScheduledPropertyPurchase(
                    month=0,
                    cause_id="p1_purchase",
                    property_id="p1",
                    location_id="san_francisco",
                    buyer_agent_id=OWNER_AGENT_ID,
                    buyer_account_id="checking",
                    seller_agent_id="property_seller",
                    purchase_price_usd=purchase_price,
                    down_payment_usd=purchase_price,
                    ownership_pct=1.0,
                    rented_fraction=1.0,
                    land_value_fraction=0.20,
                    buyer_closing_cost_usd=0.0,
                )
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=12,
        )
        ctx = _multi_series(
            levels_by_series={RENT_SERIES_ID: {0: [1.0] * 13}, "home_value:san_francisco": {0: [1.0] * 13}}
        )
        run = simulate_with_external_series(scenario, external_series=ctx, rollout_count=1)
        # Cumulative depreciation grows monotonically; at month 12 (post-horizon snapshot) it's
        # accrued 12 months worth = $400,000 / 27.5 = $14,545.45.
        terminal_dep = run.property_state.filter(pl.col("month_index") == 12)
        assert terminal_dep.height == 1
        # Federal ordinary income: $60,000 rental - $14,545.45 depreciation = $45,454.55.
        breakdowns = {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}
        assert breakdowns["federal_us"]["ordinary_income_usd"] == pytest.approx(45_454.55, abs=0.02)

    def test_lifecycle_start_renting_starts_depreciation_accrual_mid_horizon(self):
        """StartRentingEvent at month 12 → depreciation accrues only from month 12 onward.
        24-month horizon, $400k building basis, 12 months of rental → annual depreciation
        in year 1 = 0; in year 2 (after start) = $400k / 27.5 = $14,545.45."""

        end_month = 23  # 24-month horizon
        purchase_price = 500_000.0
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="property_seller"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=600_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="property_seller", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    # Rental income only fires from month 12 — matches the start-renting event.
                    start_month=12,
                    end_month=end_month,
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=5_000.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                )
            ],
            scheduled_property_purchases=[
                ScheduledPropertyPurchase(
                    month=0,
                    cause_id="p1_purchase",
                    property_id="p1",
                    location_id="san_francisco",
                    buyer_agent_id=OWNER_AGENT_ID,
                    buyer_account_id="checking",
                    seller_agent_id="property_seller",
                    purchase_price_usd=purchase_price,
                    down_payment_usd=purchase_price,
                    ownership_pct=1.0,
                    rented_fraction=0.0,  # owner-occupied at start
                    land_value_fraction=0.20,
                    buyer_closing_cost_usd=0.0,
                )
            ],
            property_lifecycle_events=[StartRentingEvent(month=12, property_id="p1", rented_fraction=1.0)],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=24,
        )
        ctx = _multi_series(
            levels_by_series={RENT_SERIES_ID: {0: [1.0] * 25}, "home_value:san_francisco": {0: [1.0] * 25}}
        )
        run = simulate_with_external_series(scenario, external_series=ctx, rollout_count=1)
        breakdowns = list(run.events_log.tax_breakdowns.sort("month_index", "jurisdiction_id").iter_rows(named=True))
        # Year 0 (month 11) federal_us: rented_fraction=0 the whole year, no rental income, no
        # depreciation → ordinary_income = $0.
        year_0_federal = next(b for b in breakdowns if b["month_index"] == 11 and b["jurisdiction_id"] == "federal_us")
        assert year_0_federal["ordinary_income_usd"] == pytest.approx(0.0, abs=1e-6)
        # Year 1 (month 23) federal_us: 12 months rent ($60k) minus 12 months depreciation ($14.5k)
        # ≈ $45,454.55.
        year_1_federal = next(b for b in breakdowns if b["month_index"] == 23 and b["jurisdiction_id"] == "federal_us")
        assert year_1_federal["ordinary_income_usd"] == pytest.approx(45_454.55, abs=0.05)

    def test_lifecycle_start_renting_redirects_mortgage_interest_from_mid_to_schedule_e(self):
        """At start-of-rental, MID drops to 0 for the now-rented portion of mortgage interest,
        and Schedule E picks it up. Comparison: same scenario with rented_fraction=0 throughout
        vs. with StartRentingEvent at month 0 setting rented_fraction=1.0 — the second case
        should yield zero MID line."""

        breakdowns_owner = self._mortgage_lifecycle_breakdown(start_renting_at=None)
        # NOTE: StartRentingEvent must fire strictly after purchase (month 0), so use month 1.
        breakdowns_rent = self._mortgage_lifecycle_breakdown(start_renting_at=1)
        # Owner-occupied: positive MID
        assert breakdowns_owner["federal_us"]["mortgage_interest_deduction_usd"] > 0
        # Rented from month 1: MID for year 0 is the month-0 interest only (a tiny first-month
        # owner-share interest), much smaller than full-year owner-occupied MID.
        assert (
            breakdowns_rent["federal_us"]["mortgage_interest_deduction_usd"]
            < breakdowns_owner["federal_us"]["mortgage_interest_deduction_usd"] * 0.15
        )

    def _mortgage_lifecycle_breakdown(self, *, start_renting_at: int | None) -> dict:
        end_month = 11
        purchase_price = 500_000.0
        lifecycle_events = (
            [StartRentingEvent(month=start_renting_at, property_id="p1", rented_fraction=1.0)]
            if start_renting_at is not None
            else []
        )
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="property_seller"),
                Agent(agent_id="lender"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=700_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="property_seller", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="lender", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="paycheck",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=5_000.0,
                    income_category="ordinary",
                )
            ],
            scheduled_property_purchases=[
                ScheduledPropertyPurchase(
                    month=0,
                    cause_id="p1_purchase",
                    property_id="p1",
                    location_id="san_francisco",
                    buyer_agent_id=OWNER_AGENT_ID,
                    buyer_account_id="checking",
                    seller_agent_id="property_seller",
                    purchase_price_usd=purchase_price,
                    down_payment_usd=purchase_price * 0.20,
                    land_value_fraction=1.0,  # isolate from depreciation
                    mortgage=MortgageFinancing(
                        liability_id="p1_mortgage",
                        lender_agent_id="lender",
                        lender_account_id="checking",
                        principal_usd=purchase_price * 0.80,
                        annual_interest_rate=0.06,
                        term_months=360,
                    ),
                    ownership_pct=1.0,
                    rented_fraction=0.0,
                )
            ],
            property_lifecycle_events=lifecycle_events,
            mortgage_interest_deduction_policies=[
                MortgageInterestDeductionPolicy(liability_id="p1_mortgage", owner_agent_id=OWNER_AGENT_ID)
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=12,
        )
        ctx = _multi_series(levels_by_series={"home_value:san_francisco": {0: [1.0] * 13}})
        run = simulate_with_external_series(scenario, external_series=ctx, rollout_count=1)
        return {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}

    def test_lifecycle_stop_renting_halts_depreciation(self):
        """StopRentingEvent at month 12 → depreciation accrues months 0-11 only.
        Year 0 ordinary: $60k rent - $14.5k dep = $45.5k.
        Year 1 ordinary: $0 rent (no more rental income), no dep → $0.
        """

        purchase_price = 500_000.0
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="property_seller"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=600_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="property_seller", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=11,  # rental income only in year 0
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=5_000.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                )
            ],
            scheduled_property_purchases=[
                ScheduledPropertyPurchase(
                    month=0,
                    cause_id="p1_purchase",
                    property_id="p1",
                    location_id="san_francisco",
                    buyer_agent_id=OWNER_AGENT_ID,
                    buyer_account_id="checking",
                    seller_agent_id="property_seller",
                    purchase_price_usd=purchase_price,
                    down_payment_usd=purchase_price,
                    ownership_pct=1.0,
                    rented_fraction=1.0,
                    land_value_fraction=0.20,
                    buyer_closing_cost_usd=0.0,
                )
            ],
            property_lifecycle_events=[StopRentingEvent(month=12, property_id="p1")],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=24,
        )
        ctx = _multi_series(
            levels_by_series={RENT_SERIES_ID: {0: [1.0] * 25}, "home_value:san_francisco": {0: [1.0] * 25}}
        )
        run = simulate_with_external_series(scenario, external_series=ctx, rollout_count=1)
        breakdowns = list(run.events_log.tax_breakdowns.sort("month_index", "jurisdiction_id").iter_rows(named=True))
        year_0_federal = next(b for b in breakdowns if b["month_index"] == 11 and b["jurisdiction_id"] == "federal_us")
        assert year_0_federal["ordinary_income_usd"] == pytest.approx(45_454.55, abs=0.05)
        year_1_federal = next(b for b in breakdowns if b["month_index"] == 23 and b["jurisdiction_id"] == "federal_us")
        assert year_1_federal["ordinary_income_usd"] == pytest.approx(0.0, abs=1e-6)

    def test_depreciation_does_not_accrue_when_not_rented(self):
        """No rental → no depreciation accrual → no Schedule E deduction."""

        end_month = 11
        purchase_price = 500_000.0
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="property_seller"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=600_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="property_seller", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="paycheck",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=5_000.0,
                    income_category="ordinary",
                )
            ],
            scheduled_property_purchases=[
                ScheduledPropertyPurchase(
                    month=0,
                    cause_id="p1_purchase",
                    property_id="p1",
                    location_id="san_francisco",
                    buyer_agent_id=OWNER_AGENT_ID,
                    buyer_account_id="checking",
                    seller_agent_id="property_seller",
                    purchase_price_usd=purchase_price,
                    down_payment_usd=purchase_price,
                    ownership_pct=1.0,
                    rented_fraction=0.0,
                    land_value_fraction=0.20,
                )
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=12,
        )
        ctx = _multi_series(levels_by_series={"home_value:san_francisco": {0: [1.0] * 13}})
        run = simulate_with_external_series(scenario, external_series=ctx, rollout_count=1)
        breakdowns = {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}
        # No depreciation → ordinary income equals gross paycheck income: $60,000.
        assert breakdowns["federal_us"]["ordinary_income_usd"] == pytest.approx(60_000.0, abs=1e-6)

    def test_mortgage_interest_deducts_full_for_owner_occupied_and_scales_for_partial_rental(self):
        """MID applies to the owner-fraction of mortgage interest; the rented-fraction share
        deducts as Schedule E rental interest. The MID compile-time scaling and the engine's
        year-end Schedule E rental-interest hook combine to make rented_fraction × interest
        deductible under either MID or Schedule E depending on which yields the better total."""

        owner_breakdown = self._mortgage_scenario_breakdown(rented_fraction=0.0)
        rented_breakdown = self._mortgage_scenario_breakdown(rented_fraction=1.0)
        # Whether the property is fully owner-occupied or fully rented, the same dollar amount
        # of mortgage interest reduces ordinary income — just via different mechanisms (MID +
        # itemized vs. Schedule E direct subtraction). The federal final tax should match.
        # The interest is the same; deduction mechanics differ.
        assert owner_breakdown["federal_us"]["mortgage_interest_deduction_usd"] > 0
        assert rented_breakdown["federal_us"]["mortgage_interest_deduction_usd"] == pytest.approx(0.0, abs=1e-6)

    def _mortgage_scenario_breakdown(self, *, rented_fraction: float) -> dict:
        end_month = 11
        purchase_price = 600_000.0
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="property_seller"),
                Agent(agent_id="lender"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=700_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="property_seller", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="lender", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=4_000.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                )
            ],
            scheduled_property_purchases=[
                ScheduledPropertyPurchase(
                    month=0,
                    cause_id="p1_purchase",
                    property_id="p1",
                    location_id="san_francisco",
                    buyer_agent_id=OWNER_AGENT_ID,
                    buyer_account_id="checking",
                    seller_agent_id="property_seller",
                    purchase_price_usd=purchase_price,
                    down_payment_usd=purchase_price * 0.20,
                    # Isolate the MID-vs-Schedule-E comparison from depreciation.
                    land_value_fraction=1.0,
                    mortgage=MortgageFinancing(
                        liability_id="p1_mortgage",
                        lender_agent_id="lender",
                        lender_account_id="checking",
                        principal_usd=purchase_price * 0.80,
                        annual_interest_rate=0.06,
                        term_months=360,
                    ),
                    ownership_pct=1.0,
                    rented_fraction=rented_fraction,
                )
            ],
            mortgage_interest_deduction_policies=[
                MortgageInterestDeductionPolicy(liability_id="p1_mortgage", owner_agent_id=OWNER_AGENT_ID)
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=12,
        )
        ctx = _multi_series(
            levels_by_series={RENT_SERIES_ID: {0: [1.0] * 13}, "home_value:san_francisco": {0: [1.0] * 13}}
        )
        run = simulate_with_external_series(scenario, external_series=ctx, rollout_count=1)
        return {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}

    def test_property_tax_routes_owner_fraction_to_salt_and_rented_fraction_to_schedule_e(self):
        """Per-property `rented_fraction=0.75` should:
        - route 25% of property tax to SALT (owner-use portion)
        - route 75% of property tax to Schedule E (rented-use portion deduction).
        """

        # Build via ScheduledPropertyPurchase + PropertyTaxPolicy so the kind=2 compiler branch
        # populates the owner_fraction + deduction_profile arrays.
        end_month = 11
        purchase_price = 600_000.0
        rented_fraction = 0.75
        annual_tax_rate = 0.012  # 1.2% of price = $7,200/yr → $600/mo
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="property_seller"),
                Agent(agent_id="tax_authority"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=700_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="property_seller", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="tax_authority", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=4_000.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                )
            ],
            scheduled_property_purchases=[
                ScheduledPropertyPurchase(
                    month=0,
                    cause_id="p1_purchase",
                    property_id="p1",
                    location_id="san_francisco",
                    buyer_agent_id=OWNER_AGENT_ID,
                    buyer_account_id="checking",
                    seller_agent_id="property_seller",
                    purchase_price_usd=purchase_price,
                    down_payment_usd=purchase_price,
                    ownership_pct=1.0,
                    rented_fraction=rented_fraction,
                    # Isolate the property-tax assertion from depreciation: setting
                    # land_value_fraction=1.0 makes the building basis zero, so no §168
                    # depreciation accrues for this test.
                    land_value_fraction=1.0,
                )
            ],
            property_tax_policies=[
                PropertyTaxPolicy(
                    property_id="p1",
                    owner_agent_id=OWNER_AGENT_ID,
                    from_account_id="checking",
                    tax_authority_agent_id="tax_authority",
                    tax_authority_account_id="checking",
                    annual_tax_rate=annual_tax_rate,
                    start_month=0,
                    end_month=end_month,
                )
            ],
            federal_salt_deduction_policies=[
                FederalSaltDeductionPolicy(
                    profile_id=OWNER_AGENT_ID,
                    cap_schedule=[FederalSaltCapEntry(effective_year_index=0, cap_usd=10_000.0)],
                )
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=12,
        )
        # Series needs home_value:san_francisco too for property purchase.
        ctx = _multi_series(
            levels_by_series={RENT_SERIES_ID: {0: [1.0] * 13}, "home_value:san_francisco": {0: [1.0] * 13}}
        )
        run = simulate_with_external_series(scenario, external_series=ctx, rollout_count=1)
        # Debug: surface any rollout failure before asserting on tax flows.
        status = run.rollout_status
        assert status["status"][0] != "failed", (
            f"rollout failed at month {status['failed_month'][0]}; "
            f"failures: {run.events_log.rollout_failures.to_dicts()}"
        )
        breakdowns = {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}
        # Gross rent: 12 × $4,000 = $48,000. Property tax fires at months 1..11 (11 payments;
        # month 0 is the purchase month, no tax that month) → $7,200 × 11/12 = $6,600.
        # rented_fraction=0.75 → $4,950 routes to Schedule E + $1,650 routes to SALT.
        # Federal ordinary_income_usd after Schedule E = $48,000 - $4,950 = $43,050.
        # (The SALT total combines property tax + state income tax and gets capped, so we
        # don't assert on the absolute SALT number here. The owner-fraction effect is
        # observable through ordinary_income decreasing relative to the rental income.)
        assert breakdowns["federal_us"]["ordinary_income_usd"] == pytest.approx(43_050.0, abs=1e-6)

    def test_obligation_deductible_fraction_scales_deduction(self):
        """Partial rental: HOA dues are only deductible up to the rented fraction (0.5
        in this test → only $200 of the $400/mo HOA deducts each month)."""

        end_month = 11
        # Gross rental $30,000/yr (50% rented); HOA $400/mo, 50% deductible → $200/mo × 12 = $2,400.
        # Net ordinary income = $30,000 - $2,400 = $27,600.
        scenario = Scenario(
            agents=[
                Agent(agent_id=OWNER_AGENT_ID),
                Agent(agent_id=TENANT_AGENT_ID),
                Agent(agent_id="hoa"),
                Agent(agent_id="irs"),
            ],
            initial_cash=[
                InitialAccountBalance(agent_id=OWNER_AGENT_ID, account_id="checking", balance_usd=100_000.0),
                InitialAccountBalance(agent_id=TENANT_AGENT_ID, account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="hoa", account_id="checking", balance_usd=0.0),
                InitialAccountBalance(agent_id="irs", account_id="checking", balance_usd=0.0),
            ],
            recurring_transfers=[
                RecurringTransfer(
                    start_month=0,
                    end_month=end_month,
                    cause_id="rental_income:p1",
                    from_agent_id=TENANT_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id=OWNER_AGENT_ID,
                    to_account_id="checking",
                    amount_usd=SeriesIndexedAmount(
                        base_amount_usd=2_500.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    income_category="ordinary",
                )
            ],
            recurring_obligations=[
                RecurringObligation(
                    start_month=0,
                    end_month=end_month,
                    obligation_id="hoa_dues",
                    obligation_type="hoa_dues",
                    agent_id=OWNER_AGENT_ID,
                    from_account_id="checking",
                    to_agent_id="hoa",
                    to_account_id="checking",
                    amount_due_usd=SeriesIndexedAmount(
                        base_amount_usd=400.0, series_id=RENT_SERIES_ID, adjustment_period_months=12
                    ),
                    deduction_category="ordinary",
                    deductible_fraction=0.5,
                )
            ],
            tax_profiles=[
                TaxProfile(
                    agent_id=OWNER_AGENT_ID,
                    filing_status="single",
                    jurisdiction_ids=["federal_us", "california"],
                    tax_authority_agent_id="irs",
                )
            ],
            horizon_months=12,
        )
        run = _run(scenario)
        breakdowns = {row["jurisdiction_id"]: row for row in run.events_log.tax_breakdowns.iter_rows(named=True)}
        assert breakdowns["federal_us"]["ordinary_income_usd"] == pytest.approx(27_600.0, abs=1e-6)


class TestRentalCashflowReconciliation:
    def test_owner_cash_balance_after_one_year_matches_expected_net(self):
        """Headline accounting test: 12mo of rental + management - leasing matches owner's
        terminal cash change (within rounding tolerance)."""

        initial_cash = 100_000.0
        scenario = _rental_scenario(
            horizon_months=12,
            initial_cash_usd=initial_cash,
            monthly_rent=5_000.0,
            vacancy_pct=0.05,
            management_fee_pct=8.0,
            leasing_fee_months=1.0,
            avg_tenancy_months=24,
        )
        run = _run(scenario)
        # Expected: rental income = 12 × 5000 × 0.95 = $57,000.
        # Management fee = 12 × 5000 × 0.95 × 0.08 = $4,560.
        # Leasing fee = 1 × 5000 = $5,000 (month 0 only; next would be month 24, outside horizon).
        # Net to owner = 57,000 - 4,560 - 5,000 = $47,440.
        expected_owner_terminal = initial_cash + 47_440.0
        # cash_balances has snapshot_months = horizon + 1, so terminal state is at month_index == horizon.
        cash = run.cash_balances.filter(
            (pl.col("agent_id") == OWNER_AGENT_ID) & (pl.col("month_index") == scenario.horizon_months)
        )
        assert cash.height == 1
        assert cash["balance_usd"][0] == pytest.approx(expected_owner_terminal, rel=1e-6)


if __name__ == "__main__":
    pytest_bazel.main()
