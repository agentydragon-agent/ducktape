from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from augur.core.local_regulation import LocalRegulation
from augur.core.market_bundle import MarketBundle
from augur.core.property_depreciation import monthly_property_depreciation_usd
from augur.core.scenario_set import EventType, Scenario


@dataclass(frozen=True)
class PropertyDispositionArrays:
    purchase_closing_cost_usd: np.ndarray
    sale_closing_cost_usd: np.ndarray
    property_depreciation_usd: np.ndarray
    cumulative_property_depreciation_usd: np.ndarray
    property_sale_gross_usd: np.ndarray
    property_sale_net_proceeds_usd: np.ndarray
    property_sale_tax_usd: np.ndarray
    property_sale_debt_payoff_usd: np.ndarray
    realized_property_gain_usd: np.ndarray
    taxable_property_gain_usd: np.ndarray
    depreciation_recapture_usd: np.ndarray
    net_property_sale_cash_flow_usd: np.ndarray
    sale_month: int | None


def property_disposition_arrays(
    scenario: Scenario,
    market_bundle: MarketBundle,
    *,
    property_value_usd: np.ndarray,
    mortgage_balance_usd: np.ndarray,
    purchase_price_usd: float,
    local_regulation: LocalRegulation,
) -> PropertyDispositionArrays:
    shape = (market_bundle.rollout_count, market_bundle.horizon_months + 1)
    if scenario.property_selection.property_id is None:
        raise ValueError(f"scenario {scenario.scenario_id!r} has no real estate disposition")

    transaction_costs = scenario.transaction_costs
    tax_profile = scenario.tax_profile
    sale_month = property_sale_month(scenario, market_bundle.horizon_months)
    purchase_closing_cost = np.zeros(shape, dtype="float64")
    purchase_closing_cost[:, 0] = purchase_price_usd * (transaction_costs.closing_cost_buy_pct / 100)
    property_depreciation = monthly_property_depreciation_usd(
        scenario,
        market_bundle,
        purchase_price_usd=purchase_price_usd,
        purchase_closing_cost_usd=float(purchase_closing_cost[0, 0]),
        sale_month=sale_month,
    )
    cumulative_depreciation = np.cumsum(property_depreciation, axis=1)

    sale_mask = np.zeros(shape, dtype="float64")
    sale_mask[:, sale_month] = 1.0
    sale_gross = property_value_usd * sale_mask
    sale_closing_cost = sale_gross * (
        (transaction_costs.closing_cost_sell_pct + local_regulation.local_transfer_tax_pct) / 100
    )
    debt_payoff = mortgage_balance_usd * sale_mask
    accumulated_depreciation_at_sale = cumulative_depreciation * sale_mask

    cost_basis = purchase_price_usd + float(purchase_closing_cost[0, 0])
    adjusted_basis = cost_basis - accumulated_depreciation_at_sale
    realized_gain = np.maximum(0.0, sale_gross - sale_closing_cost - adjusted_basis) * sale_mask
    depreciation_recapture = np.minimum(accumulated_depreciation_at_sale, realized_gain)
    capital_gain = np.maximum(0.0, realized_gain - depreciation_recapture)
    excluded_capital_gain = np.minimum(capital_gain, tax_profile.cap_gains_exclusion_usd)
    taxable_capital_gain = np.maximum(0.0, capital_gain - excluded_capital_gain)
    taxable_gain = depreciation_recapture + taxable_capital_gain
    recapture_rate = min(tax_profile.marginal_tax_rate, 38.3) / 100
    capital_gains_rate = tax_profile.cap_gains_rate / 100
    sale_tax = depreciation_recapture * recapture_rate + taxable_capital_gain * capital_gains_rate
    net_proceeds = sale_gross - sale_closing_cost - debt_payoff - sale_tax
    return PropertyDispositionArrays(
        purchase_closing_cost_usd=purchase_closing_cost,
        sale_closing_cost_usd=sale_closing_cost,
        property_depreciation_usd=property_depreciation,
        cumulative_property_depreciation_usd=cumulative_depreciation,
        property_sale_gross_usd=sale_gross,
        property_sale_net_proceeds_usd=net_proceeds,
        property_sale_tax_usd=sale_tax,
        property_sale_debt_payoff_usd=debt_payoff,
        realized_property_gain_usd=realized_gain,
        taxable_property_gain_usd=taxable_gain,
        depreciation_recapture_usd=depreciation_recapture,
        net_property_sale_cash_flow_usd=net_proceeds,
        sale_month=sale_month,
    )


def empty_property_disposition_arrays(market_bundle: MarketBundle) -> PropertyDispositionArrays:
    zeros = np.zeros((market_bundle.rollout_count, market_bundle.horizon_months + 1), dtype="float64")
    return PropertyDispositionArrays(
        purchase_closing_cost_usd=zeros,
        sale_closing_cost_usd=zeros,
        property_depreciation_usd=zeros,
        cumulative_property_depreciation_usd=zeros,
        property_sale_gross_usd=zeros,
        property_sale_net_proceeds_usd=zeros,
        property_sale_tax_usd=zeros,
        property_sale_debt_payoff_usd=zeros,
        realized_property_gain_usd=zeros,
        taxable_property_gain_usd=zeros,
        depreciation_recapture_usd=zeros,
        net_property_sale_cash_flow_usd=zeros,
        sale_month=None,
    )


def property_sale_month(scenario: Scenario, horizon_months: int) -> int:
    explicit_sale_months = [
        int(event.month_index)
        for event in scenario.events
        if event.event_type is EventType.PROPERTY_SALE
        and (event.property_id is None or event.property_id == scenario.property_selection.property_id)
    ]
    if explicit_sale_months:
        return max(0, min(*explicit_sale_months, horizon_months))

    explicit_end_months: list[int] = []
    if scenario.occupancy_plan.end_month is not None:
        explicit_end_months.append(int(scenario.occupancy_plan.end_month))
    if scenario.rental_plan.end_month is not None:
        explicit_end_months.append(int(scenario.rental_plan.end_month))
    if explicit_end_months:
        return max(0, min(max(explicit_end_months), horizon_months))
    return horizon_months
