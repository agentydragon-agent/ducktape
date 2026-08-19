"""Decode a `SimulationRun` into product-shaped metrics and events.

Per-month metric reductions take a `rollout_index` and read that column directly out of a
(possibly batched) run's dense buffers; event decoding operates on an already-R=1 run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import numpy as np
import polars as pl

from finance.augur.model.series import HomeValueKey, LocationId
from finance.augur.product.asset_key import AssetKey, PrivateEquityAssetKey, asset_price_key, parse_asset_key
from finance.augur.product.metric_composition import DERIVED_METRIC_NAMES, compose_metric
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
    TerminalMetrics,
)
from finance.augur.sim.codec.plan import SimulationRun
from finance.augur.sim.scenario import ObligationType

_TAX_PAYMENT_OBLIGATION_TYPES = (ObligationType.ESTIMATED_TAX, ObligationType.TAX_TRUE_UP)


def _quanta(value: int | np.integer[Any]) -> str:
    """Serialize one authoritative integer count without a JS-number boundary."""

    return str(value)


def _value_quanta_from_quantity(
    quantity_quanta: np.ndarray, price_quanta: np.ndarray, quantity_scale: int
) -> np.ndarray:
    """Value integer asset quanta using the engine's nearest-half-up policy."""

    return _scale_quanta_by_ratio(quantity_quanta, price_quanta, np.asarray(quantity_scale, dtype=np.int64))


def _scale_quanta_by_ratio(
    amount_quanta: int | np.ndarray, numerator: np.ndarray, denominator: np.ndarray
) -> np.ndarray:
    """Apply an integer ratio with half-up rounding and no large direct product.

    Used both for quantity valuation and for property values indexed from their
    purchase-month level. Keeping the division integral prevents large values
    from overflowing or losing individual quanta before the product response.
    """

    amount = np.asarray(amount_quanta, dtype=np.int64)
    numerator = np.asarray(numerator, dtype=np.int64)
    safe_denominator = np.where(denominator > 0, denominator, 1)
    sign = np.where((amount < 0) ^ (numerator < 0), -1, 1)
    absolute_amount = np.abs(amount)
    absolute_numerator = np.abs(numerator)
    common_factor = np.gcd(absolute_numerator, safe_denominator)
    reduced_numerator = absolute_numerator // np.where(common_factor > 0, common_factor, 1)
    reduced_denominator = safe_denominator // np.where(common_factor > 0, common_factor, 1)
    amount_quotient, amount_remainder = divmod(absolute_amount, reduced_denominator)
    whole = amount_quotient * reduced_numerator
    fractional_product = amount_remainder * reduced_numerator
    fractional_quotient, fractional_remainder = divmod(fractional_product, reduced_denominator)
    rounded_fraction = fractional_quotient + (fractional_remainder >= (reduced_denominator + 1) // 2)
    return cast(np.ndarray, (sign * (whole + rounded_fraction)).astype(np.int64))


def monthly_metric_arrays_batch(dense: SimulationRun, *, primary_agent_id: str) -> dict[str, np.ndarray]:
    """Per-month product metrics for **every** rollout of a batched result as `{name: (H+1, R)}`.

    Each metric is reduced over the whole `(…, R)` batch in one vectorized pass. `month_index` is
    the shared `(H+1,)` axis (no rollout dimension).
    """

    plan = dense.plan
    primary_agent_code = _required_string_code(plan.strings, primary_agent_id)
    cash_quanta = _cash_by_month(dense, primary_agent_code=primary_agent_code)
    holding_value_quanta = _holding_value_by_month(dense, primary_agent_code=primary_agent_code)
    private_equity_value_quanta = _private_equity_value_by_month(dense, primary_agent_code=primary_agent_code)
    property_value_quanta = _property_value_by_month(dense, primary_agent_code=primary_agent_code)
    mortgage_balance_quanta = _mortgage_balance_by_month(dense, primary_agent_code=primary_agent_code)
    bond_value_quanta = _bond_value_by_month(dense, primary_agent_code=primary_agent_code)
    base = {
        "cash_quanta": cash_quanta,
        "holding_value_quanta": holding_value_quanta,
        "private_equity_value_quanta": private_equity_value_quanta,
        "property_value_quanta": property_value_quanta,
        "mortgage_balance_quanta": mortgage_balance_quanta,
        "bond_value_quanta": bond_value_quanta,
        "shortfall_quanta": _shortfall_by_month(dense, primary_agent_code=primary_agent_code),
    }
    # The derived sums come from `metric_composition` — the same definitions the engine's
    # on-device path composes — so the two cannot disagree about what net worth is.
    return {
        "month_index": np.arange(plan.horizon_months + 1, dtype=np.int64),
        **base,
        **{name: compose_metric(name, base.__getitem__) for name in DERIVED_METRIC_NAMES},
    }


def monthly_metric_arrays(
    dense: SimulationRun, *, primary_agent_id: str, rollout_index: int = 0
) -> dict[str, np.ndarray]:
    """Per-month product metrics for one rollout (column `rollout_index`) as `{name: (H+1,)}`."""
    batch = monthly_metric_arrays_batch(dense, primary_agent_id=primary_agent_id)
    return {name: (values if name == "month_index" else values[:, rollout_index]) for name, values in batch.items()}


def terminal_metrics_from_arrays(arrays: dict[str, np.ndarray], *, failed_month_index: int | None) -> TerminalMetrics:
    """Numpy-direct terminal-metrics extraction from `monthly_metric_arrays`."""

    if arrays["month_index"].size == 0:
        raise ValueError("rollout produced no monthly metrics")
    return TerminalMetrics(
        cash_quanta=_quanta(arrays["cash_quanta"][-1]),
        holding_value_quanta=_quanta(arrays["holding_value_quanta"][-1]),
        private_equity_value_quanta=_quanta(arrays["private_equity_value_quanta"][-1]),
        property_value_quanta=_quanta(arrays["property_value_quanta"][-1]),
        mortgage_balance_quanta=_quanta(arrays["mortgage_balance_quanta"][-1]),
        bond_value_quanta=_quanta(arrays["bond_value_quanta"][-1]),
        home_equity_quanta=_quanta(arrays["home_equity_quanta"][-1]),
        liquid_net_worth_quanta=_quanta(arrays["liquid_net_worth_quanta"][-1]),
        net_worth_quanta=_quanta(arrays["net_worth_quanta"][-1]),
        shortfall_quanta=_quanta(arrays["shortfall_quanta"].sum()),
        failed_month_index=failed_month_index,
    )


def failed_month_index_batch(dense: SimulationRun) -> np.ndarray:
    """Per-rollout failure month at the final snapshot; `NO_CODE` (-1) = never failed. Shape `(R,)`."""
    return cast(np.ndarray, dense.buffers.state.rollout_failed_month_state[-1, :])


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


def _cash_by_month(dense: SimulationRun, *, primary_agent_code: int) -> np.ndarray:
    cash_slots = np.flatnonzero(dense.plan.cash_agent_codes == primary_agent_code)
    return np.asarray(dense.buffers.state.cash_state[:, cash_slots, :].sum(axis=1), dtype=np.int64)


def _holding_value_by_month(dense: SimulationRun, *, primary_agent_code: int) -> np.ndarray:
    """Sum of liquid-holding lots (stocks + crypto) priced at sampled series.

    Excludes private-equity lots: PE is illiquid (saleable only at tender events) so it
    doesn't count toward liquid net worth. PE valuation surfaces separately via
    `_private_equity_value_by_month`.
    """

    return _lot_value_by_month(
        dense, primary_agent_code=primary_agent_code, include=lambda asset: not isinstance(asset, PrivateEquityAssetKey)
    )


def _private_equity_value_by_month(dense: SimulationRun, *, primary_agent_code: int) -> np.ndarray:
    """Sum of private-equity lots priced at the latest sampled mark for each issuer."""

    return _lot_value_by_month(
        dense, primary_agent_code=primary_agent_code, include=lambda asset: isinstance(asset, PrivateEquityAssetKey)
    )


def _lot_value_by_month(
    dense: SimulationRun, *, primary_agent_code: int, include: Callable[[AssetKey], bool]
) -> np.ndarray:
    plan = dense.plan
    values = np.zeros((plan.horizon_months + 1, plan.rollout_count), dtype=np.int64)
    series_index_by_id = {key: index for index, key in enumerate(plan.series_keys)}
    pe_issuer_index = {str(issuer_id): idx for idx, issuer_id in enumerate(plan.pe_issuers.issuer_ids)}
    for lot in range(plan.lot_id_codes.shape[0]):
        if int(plan.lot_agent_codes[lot]) != primary_agent_code:
            continue
        asset = plan.assets[int(plan.lot_asset_codes[lot])]
        if not include(asset):
            continue
        quantity = dense.buffers.state.lot_state[:, lot, :]  # integer quantity quanta, (H+1, R)
        # Price inputs are integer scenario-currency quantum counts. Both source
        # arrays are stored R-major `(…, R, months)`, so transpose to the
        # `(months, R)` metric layout.
        if isinstance(asset, PrivateEquityAssetKey):
            issuer_idx = pe_issuer_index.get(str(asset.issuer_id))
            if issuer_idx is None:
                raise ValueError(f"holding asset {asset.wire_id!r} has no compiled PE channels")
            price = plan.pe_channels.mark_quanta[issuer_idx, :, :].T
        else:
            series_index = series_index_by_id.get(asset_price_key(asset))
            if series_index is None:
                raise ValueError(
                    f"holding asset {asset.wire_id!r} has no modeled price series in the compiled simulation"
                )
            price = plan.external_money_values[series_index, :, :].T
        values += _value_quanta_from_quantity(quantity, price, int(plan.lot_quantity_scale[lot]))
    return np.maximum(values, 0)


def _shortfall_by_month(dense: SimulationRun, *, primary_agent_code: int) -> np.ndarray:
    plan = dense.plan
    shortfall = np.zeros((plan.horizon_months + 1, plan.rollout_count), dtype=np.int64)
    primary_obligations = plan.obligations.agent == primary_agent_code  # [H, O]
    shortfall[1:] = (dense.buffers.obligations.shortfall * primary_obligations[:, :, None].astype(np.int64)).sum(axis=1)
    return shortfall


def _required_string_code(strings: tuple[str, ...], value: str) -> int:
    try:
        return strings.index(value)
    except ValueError as exc:
        raise ValueError(f"compiled simulation string table does not contain {value!r}") from exc


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


def _property_value_by_month(dense: SimulationRun, *, primary_agent_code: int) -> np.ndarray:
    plan = dense.plan
    values = np.zeros((plan.horizon_months + 1, plan.rollout_count), dtype=np.int64)
    series_index_by_id = {key: index for index, key in enumerate(plan.series_keys)}
    for prop in range(plan.properties.id.shape[0]):
        if int(plan.properties.buyer_agent[prop]) != primary_agent_code:
            continue
        active = dense.buffers.state.property_active_state[:, prop, :]  # (H+1, R) bool
        purchase_month = int(plan.properties.month[prop])
        if purchase_month < 0:
            continue
        location_id = plan.strings[int(plan.properties.location_id[prop])]
        series_index = series_index_by_id.get(HomeValueKey(location_id=LocationId(location_id)))
        if series_index is None:
            continue
        levels = plan.external_money_values[series_index, :, :].T  # (H+1, R)
        # State snapshots are H+1 rows: index 0 = pre-month-0 opening, index s = end of month s-1.
        # The property is active starting at snapshot index `purchase_month + 1` (end of purchase month).
        base_level = levels[purchase_month]  # (R,) per-rollout base value at the purchase month
        purchase_price = int(plan.properties.purchase_price[prop])
        # Per rollout: market = purchase_price × level / base_level. Rollouts whose base level never
        # resolved (0) contribute nothing for this property (the R=1 path skipped it via `continue`).
        market = _scale_quanta_by_ratio(purchase_price, levels, base_level[None, :])
        values += np.where(active & (base_level[None, :] > 0), market, 0)
    return values


def _bond_value_by_month(dense: SimulationRun, *, primary_agent_code: int) -> np.ndarray:
    """Face still on the books each month, for the primary agent's bonds.

    A par bond held to maturity is never marked, so its value is its face and the whole
    series is a compile-time constant — identical across rollouts. Failed rollouts are
    zeroed to match every other term, which the engine does via its own failure mask; this
    has to reproduce it because bonds carry no state for the failure freeze to act on.
    """

    plan = dense.plan
    face = np.where(plan.bonds.agent == primary_agent_code, plan.bonds.face, 0)
    if plan.bonds.indexed.any():
        # A TIPS is carried at CPI-scaled principal, not par — otherwise net worth understates
        # it in exactly the inflationary scenarios the ladder is held for. Rollout-varying, so
        # this branch cannot use the constant broadcast below.
        levels = plan.external_values[np.maximum(plan.bonds.cpi_series, 0)]  # (bond, R, month)
        base = np.take_along_axis(levels, plan.bonds.index_base_month[:, None, None], axis=2)
        principal = np.round(face[:, None, None] * levels / np.where(base > 0, base, 1.0))
        carried = np.where((plan.bonds.indexed > 0)[:, None, None], principal, face[:, None, None])
        value = np.asarray(np.einsum("mb,brm->mr", plan.bonds.on_books, carried), dtype=np.int64)
    else:
        per_month = np.asarray(plan.bonds.on_books @ face, dtype=np.int64)  # (H+1,)
        value = np.broadcast_to(per_month[:, None], (plan.horizon_months + 1, plan.rollout_count)).copy()
    failed_month = failed_month_index_batch(dense)
    months = np.arange(plan.horizon_months + 1)[:, None]
    # Strictly greater, matching every other term. Snapshot `i` is the state ENTERING month `i`,
    # so a rollout that fails DURING month `m` still has a real snapshot at `m` — cash and
    # holdings both keep theirs. `>=` zeroed the opening snapshot too, which showed a portfolio
    # losing its ladder one month before it lost anything else.
    return np.where((failed_month[None, :] >= 0) & (months > failed_month[None, :]), 0, value).astype(np.int64)


def _mortgage_balance_by_month(dense: SimulationRun, *, primary_agent_code: int) -> np.ndarray:
    plan = dense.plan
    balance = np.zeros((plan.horizon_months + 1, plan.rollout_count), dtype=np.int64)
    for lia in range(plan.liabilities.codes.shape[0]):
        if int(plan.liabilities.agent[lia]) != primary_agent_code:
            continue
        balance += np.asarray(dense.buffers.state.liability_principal_state[:, lia, :], dtype=np.int64)
    return balance


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
