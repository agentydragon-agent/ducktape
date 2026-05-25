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
    InitialAccountBalance,
    RecurringObligation,
    RecurringTransfer,
    Scenario,
    ScheduledTransfer,
    SeriesIndexedAmount,
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
