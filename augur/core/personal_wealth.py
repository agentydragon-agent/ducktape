from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from augur.core._num import finite_or, require_finite as assert_finite
from augur.core.scenario_set import PrivateEquityTenderRebalancePolicy
from augur.core.schemas import (
    MonthlySalePathRow,
    NetWorthRow,
    PrivateEquityEvent,
    PrivateEquityLiquidityPath,
    PrivateEquityLiquidityRow,
    PrivateEquityPath,
    PrivateEquitySale,
)

MONTHS_PER_YEAR = 12


def portfolio_growth_factor(
    portfolio_multipliers: list[float], from_month_index: int, to_month_index: int, require_path: bool = False
) -> float:
    from_value = portfolio_multipliers[from_month_index] if from_month_index < len(portfolio_multipliers) else None
    to_value = portfolio_multipliers[to_month_index] if to_month_index < len(portfolio_multipliers) else None
    if (
        from_value is not None
        and math.isfinite(from_value)
        and from_value > 0
        and to_value is not None
        and math.isfinite(to_value)
    ):
        return to_value / from_value
    if require_path:
        raise ValueError(
            f"Missing portfolio multiplier path for OpenAI sale proceeds: {from_month_index}->{to_month_index}"
        )
    return 1


def after_tax_unit_value(price: float, basis: float, tax_rate: float) -> float:
    taxable_gain = max(0, price - basis)
    return price - taxable_gain * tax_rate


def sale_proceeds_for_units(units: float, price: float, basis: float, tax_rate: float) -> float:
    return units * after_tax_unit_value(price, basis, tax_rate)


def invested_proceeds_at_month(
    sales: list[PrivateEquitySale], portfolio_multipliers: list[float], month_index: int
) -> float:
    return sum(
        sale.after_tax_proceeds_usd
        * portfolio_growth_factor(portfolio_multipliers, sale.month_index, month_index, True)
        for sale in sales
    )


def event_sale_capacity(event: PrivateEquityEvent, remaining_units: float) -> float:
    if event.event_type == "acquisition":
        return remaining_units
    saleable = event.saleable_fraction if event.saleable_fraction is not None else 0
    return remaining_units * np.clip(saleable, 0, 1)


def guardrail_sale_units(
    *,
    allowed_units: float,
    after_tax_per_unit: float,
    liquid_before_sale: float,
    remaining_units: float,
    minimum_liquid_reserve: float,
    target_max_net_worth_pct: float,
    sale_mode: str,
) -> float:
    if allowed_units <= 0 or after_tax_per_unit <= 0:
        return 0
    reserve_need_units = max(0, minimum_liquid_reserve - liquid_before_sale) / after_tax_per_unit
    if sale_mode == "liquidity_only":
        return np.clip(reserve_need_units, 0, allowed_units)
    if sale_mode == "never_automatic":
        return 0
    target = np.clip(target_max_net_worth_pct / 100, 0.01, 0.99)
    max_private_equity_value_after_sale = (target / (1 - target)) * max(0, liquid_before_sale)
    target_remaining_units = max_private_equity_value_after_sale / after_tax_per_unit
    concentration_units = max(0, remaining_units - target_remaining_units)
    return np.clip(max(reserve_need_units, concentration_units), 0, allowed_units)


def build_private_equity_liquidity_path(
    *,
    base_liquid_path: list[float],
    private_equity_path: PrivateEquityPath | None,
    cash_usd: float,
    private_equity_units: float,
    private_equity_basis_per_unit_usd: float,
    minimum_liquid_reserve_usd: float,
    rebalance_policy: PrivateEquityTenderRebalancePolicy,
    portfolio_multipliers: list[float] | None = None,
) -> PrivateEquityLiquidityPath:
    if not base_liquid_path:
        raise ValueError("Missing base liquid path for personal wealth rollout")
    portfolio_multipliers = portfolio_multipliers or []
    path = private_equity_path
    hold_months = max(0, len(base_liquid_path) - 1)
    has_private_equity_holdings = private_equity_units > 0
    tax_rate = np.clip(rebalance_policy.tax_rate_pct / 100, 0, 0.8)
    basis = private_equity_basis_per_unit_usd
    remaining_units = private_equity_units
    sales: list[PrivateEquitySale] = []
    events_by_month: defaultdict[int, list[PrivateEquityEvent]] = defaultdict(list)

    if has_private_equity_holdings:
        if path is None:
            raise ValueError("Missing private-equity model path for nonzero private-equity holdings")
        if len(path.price_path) < hold_months + 1:
            raise ValueError("Missing private-equity model price path for nonzero private-equity holdings")

    for event in path.events if path is not None else []:
        events_by_month[event.month_index].append(event)

    rows: list[PrivateEquityLiquidityRow] = []
    for month_index in range(hold_months + 1):
        if has_private_equity_holdings:
            current_price = assert_finite(path.price_path[month_index], f"privateEquityPath.pricePath[{month_index}]")
        elif path is not None and month_index < len(path.price_path):
            current_price = finite_or(path.price_path[month_index], path.current_price_usd or 0)
        else:
            current_price = finite_or(path.current_price_usd if path is not None else 0, 0)
        base_liquid_for_month = assert_finite(base_liquid_path[month_index], f"baseLiquidPath[{month_index}]")
        liquid_before_sale = (
            base_liquid_for_month + cash_usd + invested_proceeds_at_month(sales, portfolio_multipliers, month_index)
        )
        month_sales: list[PrivateEquitySale] = []
        for event in events_by_month.get(month_index, []):
            if remaining_units <= 0:
                break
            event_price = (
                assert_finite(event.price_usd_per_unit, f"privateEquityPath.events[{month_index}].priceUsdPerUnit")
                if has_private_equity_holdings
                else finite_or(event.price_usd_per_unit, current_price)
            )
            allowed_units = event_sale_capacity(event, remaining_units)
            after_tax_per_unit = after_tax_unit_value(event_price, basis, tax_rate)
            sale_units = guardrail_sale_units(
                allowed_units=allowed_units,
                after_tax_per_unit=after_tax_per_unit,
                liquid_before_sale=liquid_before_sale,
                remaining_units=remaining_units,
                minimum_liquid_reserve=minimum_liquid_reserve_usd,
                target_max_net_worth_pct=rebalance_policy.target_max_net_worth_pct,
                sale_mode=rebalance_policy.sale_mode,
            )
            if sale_units <= 0:
                continue
            sale = PrivateEquitySale(
                month_index=month_index,
                event_type=event.event_type,
                units=sale_units,
                price_usd_per_unit=event_price,
                after_tax_proceeds_usd=sale_proceeds_for_units(sale_units, event_price, basis, tax_rate),
            )
            sales.append(sale)
            month_sales.append(sale)
            remaining_units -= sale_units
            liquid_before_sale += sale.after_tax_proceeds_usd

        liquid_private_equity_proceeds = invested_proceeds_at_month(sales, portfolio_multipliers, month_index)
        after_tax_mark_value = sale_proceeds_for_units(remaining_units, current_price, basis, tax_rate)
        base_liquid = base_liquid_for_month + cash_usd
        rows.append(
            PrivateEquityLiquidityRow(
                month_index=month_index,
                base_liquid_usd=base_liquid,
                liquid_private_equity_proceeds_usd=liquid_private_equity_proceeds,
                liquid_net_worth_contribution_usd=base_liquid + liquid_private_equity_proceeds,
                private_equity_after_tax_mark_value_usd=after_tax_mark_value,
                private_equity_units_remaining=remaining_units,
                private_equity_units_sold=max(0, private_equity_units - remaining_units),
                liquidity_shortfall=base_liquid + liquid_private_equity_proceeds < minimum_liquid_reserve_usd,
                sales=list(month_sales),
            )
        )

    return PrivateEquityLiquidityPath(
        rows=rows,
        sales=sales,
        terminal=rows[-1],
        had_liquidity_shortfall=any(row.liquidity_shortfall for row in rows),
        had_eligible_sale=len(sales) > 0,
    )


def build_net_worth_rows(
    *, monthly_sale_path: list[MonthlySalePathRow], private_equity_liquidity_path: PrivateEquityLiquidityPath
) -> list[NetWorthRow]:
    rows: list[NetWorthRow] = []
    for index, row in enumerate(monthly_sale_path):
        pe_row = private_equity_liquidity_path.rows[index]
        private_equity_liquid = pe_row.liquid_private_equity_proceeds_usd
        private_equity_mark = pe_row.private_equity_after_tax_mark_value_usd
        rows.append(
            NetWorthRow(
                month_index=row.month_index,
                rent_path_usd=row.rent_path_usd,
                buy_liquid_usd=row.buy_liquid_usd,
                buy_locked_equity_usd=row.buy_locked_equity_usd,
                buy_path_usd=row.buy_path_usd,
                sp500_usd=row.sp500_usd,
                own_usd=row.own_usd,
                delta_usd=row.delta_usd,
                project_buy_liquid_usd=row.project_buy_liquid_usd,
                project_own_usd=row.project_own_usd,
                project_delta_usd=row.project_delta_usd,
                net_sale_proceeds_usd=row.net_sale_proceeds_usd,
                gross_equity_usd=row.gross_equity_usd,
                owner_sale_claim_usd=row.owner_sale_claim_usd,
                owner_equity_ledger_usd=row.owner_equity_ledger_usd,
                liquid_net_worth_usd=round(row.buy_liquid_usd + private_equity_liquid),
                economic_net_worth_usd=round(row.buy_path_usd + private_equity_liquid + private_equity_mark),
                private_equity_liquid_value_usd=round(private_equity_liquid),
                private_equity_event_pv_usd=round(private_equity_mark),
                private_equity_units_remaining=pe_row.private_equity_units_remaining,
                liquidity_shortfall=pe_row.liquidity_shortfall,
            )
        )
    return rows
