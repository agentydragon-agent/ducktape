from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from augur.core.local_regulation import LocalRegulation
from augur.core.market_bundle import MarketBundle
from augur.core.property_depreciation import monthly_property_depreciation_usd
from augur.core.scenario_set import PropertySaleEvent, Scenario, TaxFilingStatus

PRIMARY_RESIDENCE_CAPITAL_GAIN_EXCLUSION_USD: dict[TaxFilingStatus, float] = {
    TaxFilingStatus.SINGLE: 250_000.0,
    TaxFilingStatus.HEAD_OF_HOUSEHOLD: 250_000.0,
    TaxFilingStatus.MARRIED_FILING_JOINTLY: 500_000.0,
    TaxFilingStatus.MARRIED_FILING_SEPARATELY: 0.0,
}


# Flat column namespace carried in `PropertyDispositionArrays.numerics`.
# Collapses what used to be a two-level namespace (the disposition-level
# fields + the `sale_settlement.*` nested fields) into one wide frame
# keyed by `(rollout_index, month_index)`.
_PROPERTY_DISPOSITION_COLUMNS: tuple[str, ...] = (
    "purchase_closing_cost_usd",
    "property_depreciation_usd",
    "cumulative_property_depreciation_usd",
    "property_sale_gross_usd",
    "sale_closing_cost_usd",
    "property_sale_debt_payoff_usd",
    "property_sale_adjusted_basis_usd",
    "realized_property_gain_usd",
    "property_sale_capital_gain_usd",
    "property_sale_capital_gain_exclusion_usd",
    "taxable_property_capital_gain_usd",
    "taxable_property_gain_usd",
    "depreciation_recapture_usd",
    "property_sale_tax_usd",
    "property_sale_net_proceeds_usd",
    "net_property_sale_cash_flow_usd",
)


def _build_property_disposition_frame(arrays: dict[str, np.ndarray]) -> pl.DataFrame:
    """Build a `PropertyDispositionArrays.numerics` frame from a dict of
    `(rollouts, months+1)` ndarrays, one per column in
    `_PROPERTY_DISPOSITION_COLUMNS`. Flattens rollout-major so `column()`
    can reshape back without copy."""
    sample = next(iter(arrays.values()))
    n_rollouts, n_months_plus_one = sample.shape
    return pl.DataFrame(
        {
            "rollout_index": np.repeat(np.arange(n_rollouts, dtype=np.int32), n_months_plus_one),
            "month_index": np.tile(np.arange(n_months_plus_one, dtype=np.int32), n_rollouts),
            **{name: arrays[name].reshape(-1) for name in _PROPERTY_DISPOSITION_COLUMNS},
        }
    )


@dataclass(frozen=True)
class PropertyDispositionArrays:
    """Per-rollout-per-month property disposition state. The 16 numeric
    columns (purchase + depreciation + sale-settlement outputs) live in
    `numerics`; `sale_event` and `sale_month` are scenario-scope scalars."""

    rollout_count: int
    horizon_months: int
    numerics: pl.DataFrame
    sale_event: PropertySaleEvent | None
    sale_month: int | None

    def column(self, name: str) -> np.ndarray:
        flat: np.ndarray = self.numerics[name].to_numpy()
        return flat.reshape(self.rollout_count, self.horizon_months + 1)


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
    sale_event = property_sale_event(scenario)
    sale_month = property_sale_month(scenario, market_bundle.horizon_months)
    depreciation_through_month = sale_month if sale_month is not None else market_bundle.horizon_months
    purchase_closing_cost = np.zeros(shape, dtype="float64")
    purchase_closing_cost[:, 0] = purchase_price_usd * (transaction_costs.closing_cost_buy_pct / 100)
    property_depreciation = monthly_property_depreciation_usd(
        scenario,
        market_bundle,
        purchase_price_usd=purchase_price_usd,
        purchase_closing_cost_usd=float(purchase_closing_cost[0, 0]),
        sale_month=depreciation_through_month,
    )
    cumulative_depreciation = np.cumsum(property_depreciation, axis=1)

    sale_mask = np.zeros(shape, dtype="float64")
    if sale_month is not None:
        sale_mask[:, sale_month] = 1.0
    sale_gross = property_value_usd * sale_mask
    sale_closing_cost = sale_gross * (
        (transaction_costs.closing_cost_sell_pct + local_regulation.local_transfer_tax_pct) / 100
    )
    debt_payoff = mortgage_balance_usd * sale_mask
    accumulated_depreciation_at_sale = cumulative_depreciation * sale_mask

    cost_basis = purchase_price_usd + float(purchase_closing_cost[0, 0])
    adjusted_basis = (cost_basis - accumulated_depreciation_at_sale) * sale_mask
    realized_gain = np.maximum(0.0, sale_gross - sale_closing_cost - adjusted_basis) * sale_mask
    depreciation_recapture = np.minimum(accumulated_depreciation_at_sale, realized_gain)
    capital_gain = np.maximum(0.0, realized_gain - depreciation_recapture)
    exclusion_cap = PRIMARY_RESIDENCE_CAPITAL_GAIN_EXCLUSION_USD[tax_profile.filing_status]
    capital_gain_exclusion = np.minimum(capital_gain, exclusion_cap)
    taxable_capital_gain = np.maximum(0.0, capital_gain - capital_gain_exclusion)
    taxable_gain = depreciation_recapture + taxable_capital_gain
    # The engine owns sale-tax computation via annual_tax.annual_sale_tax_allocation
    # (bracket-aware federal + California). Disposition stops at pre-tax proceeds; the
    # tax obligation accrues and settles through the annual-tax obligation path.
    sale_tax = np.zeros_like(sale_gross)
    net_proceeds = sale_gross - sale_closing_cost - debt_payoff
    rollout_count, n_months_plus_one = shape
    return PropertyDispositionArrays(
        rollout_count=rollout_count,
        horizon_months=n_months_plus_one - 1,
        numerics=_build_property_disposition_frame(
            {
                "purchase_closing_cost_usd": purchase_closing_cost,
                "property_depreciation_usd": property_depreciation,
                "cumulative_property_depreciation_usd": cumulative_depreciation,
                "property_sale_gross_usd": sale_gross,
                "sale_closing_cost_usd": sale_closing_cost,
                "property_sale_debt_payoff_usd": debt_payoff,
                "property_sale_adjusted_basis_usd": adjusted_basis,
                "realized_property_gain_usd": realized_gain,
                "property_sale_capital_gain_usd": capital_gain,
                "property_sale_capital_gain_exclusion_usd": capital_gain_exclusion,
                "taxable_property_capital_gain_usd": taxable_capital_gain,
                "taxable_property_gain_usd": taxable_gain,
                "depreciation_recapture_usd": depreciation_recapture,
                "property_sale_tax_usd": sale_tax,
                "property_sale_net_proceeds_usd": net_proceeds,
                "net_property_sale_cash_flow_usd": net_proceeds,
            }
        ),
        sale_event=sale_event,
        sale_month=sale_month,
    )


def empty_property_disposition_arrays(market_bundle: MarketBundle) -> PropertyDispositionArrays:
    zeros = np.zeros((market_bundle.rollout_count, market_bundle.horizon_months + 1), dtype="float64")
    return PropertyDispositionArrays(
        rollout_count=market_bundle.rollout_count,
        horizon_months=market_bundle.horizon_months,
        numerics=_build_property_disposition_frame(dict.fromkeys(_PROPERTY_DISPOSITION_COLUMNS, zeros)),
        sale_event=None,
        sale_month=None,
    )


def property_sale_month(scenario: Scenario, horizon_months: int) -> int | None:
    sale_event = property_sale_event(scenario)
    if sale_event is None:
        return None
    return max(0, min(int(sale_event.month_index), horizon_months))


def property_sale_event(scenario: Scenario) -> PropertySaleEvent | None:
    explicit_sale_events = [
        event
        for event in scenario.events
        if isinstance(event, PropertySaleEvent)
        and (event.property_id is None or event.property_id == scenario.property_selection.property_id)
    ]
    if not explicit_sale_events:
        return None
    return min(explicit_sale_events, key=lambda event: int(event.month_index))
