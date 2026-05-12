from __future__ import annotations

import numpy as np

from augur.core.market_bundle import MarketBundle
from augur.core.scenario_set import RentalMode, Scenario

MONTHS_PER_YEAR = 12
DEPRECIATION_LIFE_YEARS = 27.5


def monthly_property_depreciation_usd(
    scenario: Scenario,
    market_bundle: MarketBundle,
    *,
    purchase_price_usd: float,
    purchase_closing_cost_usd: float,
    sale_month: int,
) -> np.ndarray:
    property_assumptions = scenario.property_assumptions
    shape = (market_bundle.rollout_count, market_bundle.horizon_months + 1)
    if property_assumptions.depreciable_basis_pct == 0:
        return np.zeros(shape, dtype="float64")
    depreciable_basis = (purchase_price_usd + purchase_closing_cost_usd) * (
        property_assumptions.depreciable_basis_pct / 100
    )
    monthly_depreciation = depreciable_basis / (DEPRECIATION_LIFE_YEARS * MONTHS_PER_YEAR)
    active = (
        (market_bundle.month_index > 0)
        & (market_bundle.month_index <= sale_month)
        & depreciation_active_mask(scenario, market_bundle)
    )
    return np.broadcast_to((monthly_depreciation * active.astype("float64"))[None, :], shape).copy()


def depreciation_active_mask(scenario: Scenario, market_bundle: MarketBundle) -> np.ndarray:
    if scenario.rental_plan.rental_mode is RentalMode.NOT_RENTED:
        return np.zeros(market_bundle.horizon_months + 1, dtype=np.bool_)
    return rental_active_mask(scenario, market_bundle)


def rental_active_mask(scenario: Scenario, market_bundle: MarketBundle) -> np.ndarray:
    rental = scenario.rental_plan
    if rental.rental_mode is RentalMode.TRANSITION_TO_WHOLE_PROPERTY_RENTAL and rental.start_month is None:
        start_month = (scenario.occupancy_plan.end_month + 1) if scenario.occupancy_plan.end_month is not None else 1
    else:
        start_month = rental.start_month if rental.start_month is not None else 1
    start_month = max(1, int(start_month))
    end_month = int(rental.end_month) if rental.end_month is not None else market_bundle.horizon_months
    month_index = market_bundle.month_index
    return (month_index >= start_month) & (month_index <= end_month)
