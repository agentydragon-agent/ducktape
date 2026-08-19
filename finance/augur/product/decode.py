"""Decode a `SimulationRun` into product-shaped event records.

Product metric series come directly from the JAX product reducer. This module
only projects selected-rollout events from the dense buffers.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from finance.augur.product.asset_key import PrivateEquityAssetKey, parse_asset_key
from finance.augur.product.wire import (
    CapitalImprovementMarkerEvent,
    ClosingCostPaymentEvent,
    HoaDuesPaymentEvent,
    HoldingSaleEvent,
    HomeownersInsurancePaymentEvent,
    MonthlyExpenseEvent,
    MortgagePaymentEvent,
    OutsideRentPaymentEvent,
    PrivateEquityMarkerEvent,
    PrivateEquityOpportunityEvent,
    PropertyMaintenancePaymentEvent,
    PropertyPurchaseEvent,
    PropertySaleMarkerEvent,
    PropertyTaxPaymentEvent,
    RolloutEvent,
    RolloutFailureEvent,
    SetPrimaryResidenceMarkerEvent,
    SetRentedFractionMarkerEvent,
    TaxAccrualEvent,
    TaxPaymentEvent,
)
from finance.augur.sim.codec.plan import SimulationRun
from finance.augur.sim.scenario import ObligationType

_TAX_PAYMENT_OBLIGATION_TYPES = (ObligationType.ESTIMATED_TAX, ObligationType.TAX_TRUE_UP)


def _quanta(value: int | np.integer[Any]) -> str:
    """Serialize one authoritative integer count without a JS-number boundary."""

    return str(value)


def rollout_events_from(
    run: SimulationRun, *, primary_agent_id: str, asset_label_by_id: dict[str, str]
) -> tuple[RolloutEvent, ...]:
    events = [
        *_holding_sale_events(run, primary_agent_id=primary_agent_id, asset_label_by_id=asset_label_by_id),
        *_property_purchase_events(run, primary_agent_id=primary_agent_id),
        *_private_equity_events(run, primary_agent_id=primary_agent_id, asset_label_by_id=asset_label_by_id),
        *_private_equity_opportunities(run, primary_agent_id=primary_agent_id, asset_label_by_id=asset_label_by_id),
        *_mortgage_payment_events(run, primary_agent_id=primary_agent_id),
        *_property_tax_payment_events(run, primary_agent_id=primary_agent_id),
        *_hoa_dues_events(run, primary_agent_id=primary_agent_id),
        *_homeowners_insurance_events(run, primary_agent_id=primary_agent_id),
        *_property_maintenance_events(run, primary_agent_id=primary_agent_id),
        *_tax_accrual_events(run, primary_agent_id=primary_agent_id),
        *_tax_payment_events(run, primary_agent_id=primary_agent_id),
        *_monthly_expense_events(run, primary_agent_id=primary_agent_id),
        *_outside_rent_events(run, primary_agent_id=primary_agent_id),
        *_failure_events(run, primary_agent_id=primary_agent_id),
        *_set_rented_fraction_events(run),
        *_set_primary_residence_events(run, primary_agent_id=primary_agent_id),
        *_capital_improvement_events(run),
        *_property_sale_events(run),
    ]
    priority = {
        "property_purchase": 0,
        "closing_cost_payment": 1,
        "set_primary_residence": 2,
        "set_rented_fraction": 3,
        "capital_improvement": 4,
        "property_sale": 5,
        "private_equity_event": 6,
        "private_equity_opportunity": 7,
        "holding_sale": 8,
        "tax_accrual": 9,
        "tax_payment": 10,
        "property_tax_payment": 11,
        "hoa_dues_payment": 12,
        "homeowners_insurance_payment": 13,
        "property_maintenance_payment": 14,
        "mortgage_payment": 15,
        "monthly_expense": 16,
        "outside_rent": 17,
        "failure": 18,
    }
    return tuple(sorted(events, key=lambda event: (event.month_index, priority[event.kind])))


def _holding_sale_events(
    run: SimulationRun, *, primary_agent_id: str, asset_label_by_id: dict[str, str]
) -> tuple[RolloutEvent, ...]:
    sale_rows = (
        run.events_log.lot_dispositions.filter(pl.col("agent_id") == primary_agent_id)
        .group_by(["month_index", "asset_id"])
        .agg(
            pl.col("units_sold").sum(),
            pl.col("proceeds_quanta").sum(),
            pl.col("cost_basis_consumed_quanta").sum().alias("cost_basis_quanta"),
        )
        .sort("month_index", "asset_id")
    )
    return tuple(
        HoldingSaleEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["proceeds_quanta"]),
            asset=parse_asset_key(str(row["asset_id"])),
            asset_label=asset_label_by_id.get(str(row["asset_id"])),
            units=float(row["units_sold"]),
            proceeds_quanta=_quanta(row["proceeds_quanta"]),
            cost_basis_quanta=_quanta(row["cost_basis_quanta"]),
        )
        for row in sale_rows.iter_rows(named=True)
    )


def _private_equity_events(
    run: SimulationRun, *, primary_agent_id: str, asset_label_by_id: dict[str, str]
) -> tuple[RolloutEvent, ...]:
    # Filter PE asset rows by classifying each asset_id through the typed
    # `AssetKey` discriminator; polars itself can't dispatch on Python types,
    # but we can compute the set of PE asset wire ids in Python and use `is_in`.
    primary_assets = (
        run.asset_lots.filter(pl.col("agent_id") == primary_agent_id)
        .select("asset_id")
        .unique()
        .get_column("asset_id")
        .to_list()
    )
    primary_pe_assets = {
        asset_id for asset_id in primary_assets if isinstance(parse_asset_key(str(asset_id)), PrivateEquityAssetKey)
    }
    if not primary_pe_assets:
        return ()
    rows = run.events_log.private_equity_events.filter(pl.col("asset_id").is_in(primary_pe_assets)).sort(
        "month_index", "issuer_id", "event_kind"
    )
    return tuple(
        PrivateEquityMarkerEvent(
            month_index=int(row["month_index"]),
            amount_quanta="0",
            issuer_id=str(row["issuer_id"]),
            asset=parse_asset_key(str(row["asset_id"])),
            asset_label=asset_label_by_id.get(str(row["asset_id"])),
            event_kind=str(row["event_kind"]),
            regime=str(row["regime"]),
            mark_quanta=_quanta(row["mark_quanta"]),
            sale_capacity_fraction=float(row["sale_capacity_fraction"]),
            eligible_fraction=float(row["eligible_fraction"]),
            forced_sale_fraction=float(row["forced_sale_fraction"]),
            liquidity_blocked=bool(row["liquidity_blocked"]),
            forced_recovery_cashout_quanta=_quanta(row["forced_recovery_cashout_quanta"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _private_equity_opportunities(
    run: SimulationRun, *, primary_agent_id: str, asset_label_by_id: dict[str, str]
) -> tuple[RolloutEvent, ...]:
    primary_assets = (
        run.asset_lots.filter(pl.col("agent_id") == primary_agent_id)
        .select("asset_id")
        .unique()
        .get_column("asset_id")
        .to_list()
    )
    primary_pe_assets = {
        asset_id for asset_id in primary_assets if isinstance(parse_asset_key(str(asset_id)), PrivateEquityAssetKey)
    }
    if not primary_pe_assets:
        return ()
    rows = run.events_log.private_equity_opportunities.filter(pl.col("asset_id").is_in(primary_pe_assets)).sort(
        "month_index", "issuer_id", "outcome"
    )
    return tuple(
        PrivateEquityOpportunityEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["proceeds_quanta"]),
            issuer_id=str(row["issuer_id"]),
            asset=parse_asset_key(str(row["asset_id"])),
            asset_label=asset_label_by_id.get(str(row["asset_id"])),
            event_kind=str(row["event_kind"]),
            regime=str(row["regime"]),
            outcome=str(row["outcome"]),
            mark_quanta=_quanta(row["mark_quanta"]),
            sale_capacity_fraction=float(row["sale_capacity_fraction"]),
            eligible_fraction=float(row["eligible_fraction"]),
            liquidity_blocked=bool(row["liquidity_blocked"]),
            floor_quanta=_quanta(row["floor_quanta"]),
            liquid_net_worth_quanta=_quanta(row["liquid_net_worth_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
            units_held=float(row["units_held"]),
            sellable_units=float(row["sellable_units"]),
            target_units=float(row["target_units"]),
            proceeds_quanta=_quanta(row["proceeds_quanta"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _monthly_expense_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    expense_rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.CASH_SPEND)
    ).sort("month_index", "obligation_id")
    return tuple(
        MonthlyExpenseEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_paid_quanta"]),
            amount_due_quanta=_quanta(row["amount_due_quanta"]),
            amount_paid_quanta=_quanta(row["amount_paid_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
        )
        for row in expense_rows.iter_rows(named=True)
    )


def _outside_rent_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    rent_rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.OUTSIDE_RENT)
    ).sort("month_index", "obligation_id")
    return tuple(
        OutsideRentPaymentEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_paid_quanta"]),
            amount_due_quanta=_quanta(row["amount_due_quanta"]),
            amount_paid_quanta=_quanta(row["amount_paid_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
        )
        for row in rent_rows.iter_rows(named=True)
    )


def _tax_accrual_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    keys = ["rollout_index", "month_index", "cause_id", "agent_id", "jurisdiction_id", "tax_year_end_month"]
    breakdown_columns = [
        *keys,
        "ordinary_income_quanta",
        "ltcg_quanta",
        "stcg_quanta",
        "standard_deduction_quanta",
        "mortgage_interest_deduction_quanta",
        "itemized_deduction_quanta",
        "ordinary_tax_quanta",
        "capital_gain_tax_quanta",
        "total_tax_quanta",
    ]
    accrual_rows = (
        run.events_log.tax_accruals.filter(pl.col("agent_id") == primary_agent_id)
        .join(run.events_log.tax_breakdowns.select(breakdown_columns), on=keys, how="left")
        .with_columns(
            ordinary_income_quanta=pl.col("ordinary_income_quanta").fill_null(0),
            ltcg_quanta=pl.col("ltcg_quanta").fill_null(0),
            stcg_quanta=pl.col("stcg_quanta").fill_null(0),
            standard_deduction_quanta=pl.col("standard_deduction_quanta").fill_null(0),
            mortgage_interest_deduction_quanta=pl.col("mortgage_interest_deduction_quanta").fill_null(0),
            itemized_deduction_quanta=pl.col("itemized_deduction_quanta").fill_null(0),
            ordinary_tax_quanta=pl.col("ordinary_tax_quanta").fill_null(pl.col("amount_quanta")),
            capital_gain_tax_quanta=pl.col("capital_gain_tax_quanta").fill_null(0),
            total_tax_quanta=pl.col("total_tax_quanta").fill_null(pl.col("amount_quanta")),
        )
        .sort("month_index", "jurisdiction_id")
    )
    return tuple(
        TaxAccrualEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_quanta"]),
            jurisdiction_id=str(row["jurisdiction_id"]),
            tax_year_end_month=int(row["tax_year_end_month"]),
            ordinary_income_quanta=_quanta(row["ordinary_income_quanta"]),
            ltcg_quanta=_quanta(row["ltcg_quanta"]),
            stcg_quanta=_quanta(row["stcg_quanta"]),
            ordinary_tax_quanta=_quanta(row["ordinary_tax_quanta"]),
            capital_gain_tax_quanta=_quanta(row["capital_gain_tax_quanta"]),
            total_tax_quanta=_quanta(row["total_tax_quanta"]),
            mortgage_interest_deduction_quanta=_quanta(row["mortgage_interest_deduction_quanta"]),
            itemized_deduction_quanta=_quanta(row["itemized_deduction_quanta"]),
            standard_deduction_quanta=_quanta(row["standard_deduction_quanta"]),
        )
        for row in accrual_rows.iter_rows(named=True)
    )


def _tax_payment_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    tax_payment_rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & pl.col("obligation_type").is_in(_TAX_PAYMENT_OBLIGATION_TYPES)
    ).sort("month_index", "obligation_id")
    return tuple(
        TaxPaymentEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_paid_quanta"]),
            obligation_type=str(row["obligation_type"]),
            amount_due_quanta=_quanta(row["amount_due_quanta"]),
            amount_paid_quanta=_quanta(row["amount_paid_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
        )
        for row in tax_payment_rows.iter_rows(named=True)
    )


def _failure_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    failure_rows = run.events_log.rollout_failures.filter(pl.col("agent_id") == primary_agent_id)
    return tuple(
        RolloutFailureEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["shortfall_quanta"]),
            amount_due_quanta=_quanta(row["amount_due_quanta"]),
            amount_paid_quanta=_quanta(row["amount_paid_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
        )
        for row in failure_rows.iter_rows(named=True)
    )


def _property_purchase_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    primary_purchases = run.events_log.property_purchases.filter(pl.col("buyer_agent_id") == primary_agent_id)
    originations = run.events_log.mortgage_originations.select(
        pl.col("rollout_index"),
        pl.col("month_index"),
        pl.col("property_id"),
        pl.col("principal_quanta").alias("mortgage_principal_quanta"),
    )
    joined = primary_purchases.join(
        originations, on=["rollout_index", "month_index", "property_id"], how="left"
    ).with_columns(mortgage_principal_quanta=pl.col("mortgage_principal_quanta").fill_null(0))
    events: list[RolloutEvent] = []
    for row in joined.iter_rows(named=True):
        events.append(
            PropertyPurchaseEvent(
                month_index=int(row["month_index"]),
                amount_quanta=_quanta(row["purchase_price_quanta"]),
                property_id=str(row["property_id"]),
                purchase_price_quanta=_quanta(row["purchase_price_quanta"]),
                # equity_ledger_quanta = purchase_price - mortgage_principal (compiler line 866);
                # equals the cash down payment.
                down_payment_quanta=_quanta(row["equity_ledger_quanta"]),
                mortgage_principal_quanta=_quanta(row["mortgage_principal_quanta"]),
            )
        )
        closing_cost = int(row["closing_cost_quanta"])
        if closing_cost > 0:
            events.append(
                ClosingCostPaymentEvent(
                    month_index=int(row["month_index"]),
                    amount_quanta=_quanta(closing_cost),
                    property_id=str(row["property_id"]),
                )
            )
    return tuple(events)


def _mortgage_payment_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    payment_rows = run.events_log.mortgage_payments.filter(pl.col("agent_id") == primary_agent_id).sort("month_index")
    return tuple(
        MortgagePaymentEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["total_payment_quanta"]),
            interest_quanta=_quanta(row["interest_quanta"]),
            principal_quanta=_quanta(row["principal_quanta"]),
        )
        for row in payment_rows.iter_rows(named=True)
    )


def _property_tax_payment_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.PROPERTY_TAX)
    ).sort("month_index")
    return tuple(
        PropertyTaxPaymentEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_paid_quanta"]),
            amount_due_quanta=_quanta(row["amount_due_quanta"]),
            amount_paid_quanta=_quanta(row["amount_paid_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _hoa_dues_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.HOA_DUES)
    ).sort("month_index")
    return tuple(
        HoaDuesPaymentEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_paid_quanta"]),
            amount_due_quanta=_quanta(row["amount_due_quanta"]),
            amount_paid_quanta=_quanta(row["amount_paid_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _homeowners_insurance_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.HOMEOWNERS_INSURANCE)
    ).sort("month_index")
    return tuple(
        HomeownersInsurancePaymentEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_paid_quanta"]),
            amount_due_quanta=_quanta(row["amount_due_quanta"]),
            amount_paid_quanta=_quanta(row["amount_paid_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _property_maintenance_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    rows = run.events_log.obligation_settlements.filter(
        (pl.col("agent_id") == primary_agent_id) & (pl.col("obligation_type") == ObligationType.PROPERTY_MAINTENANCE)
    ).sort("month_index")
    return tuple(
        PropertyMaintenancePaymentEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_paid_quanta"]),
            amount_due_quanta=_quanta(row["amount_due_quanta"]),
            amount_paid_quanta=_quanta(row["amount_paid_quanta"]),
            shortfall_quanta=_quanta(row["shortfall_quanta"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _set_rented_fraction_events(run: SimulationRun) -> tuple[RolloutEvent, ...]:
    """Lifecycle SetRentedFraction markers. Product scenarios only model the primary owner,
    so every lifecycle event in the log belongs to a primary-owned property."""

    rows = run.events_log.set_rented_fraction_events.sort("month_index", "property_id")
    return tuple(
        SetRentedFractionMarkerEvent(
            month_index=int(row["month_index"]),
            amount_quanta="0",
            property_id=str(row["property_id"]),
            rented_fraction=float(row["rented_fraction"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _set_primary_residence_events(run: SimulationRun, *, primary_agent_id: str) -> tuple[RolloutEvent, ...]:
    rows = run.events_log.set_primary_residence_events.filter(pl.col("agent_id") == primary_agent_id).sort(
        "month_index", "agent_id"
    )
    return tuple(
        SetPrimaryResidenceMarkerEvent(
            month_index=int(row["month_index"]),
            amount_quanta="0",
            agent_id=str(row["agent_id"]),
            property_id=None if row["property_id"] is None else str(row["property_id"]),
            is_primary_residence=bool(row["is_primary_residence"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _capital_improvement_events(run: SimulationRun) -> tuple[RolloutEvent, ...]:
    rows = run.events_log.capital_improvement_events.sort("month_index", "property_id")
    return tuple(
        CapitalImprovementMarkerEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["amount_quanta"]),
            property_id=str(row["property_id"]),
        )
        for row in rows.iter_rows(named=True)
    )


def _property_sale_events(run: SimulationRun) -> tuple[RolloutEvent, ...]:
    rows = run.events_log.property_sale_events.sort("month_index", "property_id")
    return tuple(
        PropertySaleMarkerEvent(
            month_index=int(row["month_index"]),
            amount_quanta=_quanta(row["gross_proceeds_quanta"]),
            property_id=str(row["property_id"]),
            gross_proceeds_quanta=_quanta(row["gross_proceeds_quanta"]),
            mortgage_payoff_quanta=_quanta(row["mortgage_payoff_quanta"]),
            net_cash_to_owner_quanta=_quanta(row["net_cash_to_owner_quanta"]),
            realized_gain_quanta=_quanta(row["realized_gain_quanta"]),
            depreciation_recapture_quanta=_quanta(row["depreciation_recapture_quanta"]),
            section_121_exclusion_quanta=_quanta(row["section_121_exclusion_quanta"]),
            long_term_capital_gain_quanta=_quanta(row["long_term_capital_gain_quanta"]),
        )
        for row in rows.iter_rows(named=True)
    )
