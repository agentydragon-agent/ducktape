from __future__ import annotations

import numpy as np

from augur.core.local_regulation import LocalRegulation
from augur.core.market_bundle import MarketBundle

MONTHS_PER_YEAR = 12
PROP_13_ANNUAL_CAP = 1.02


def monthly_property_tax_usd(
    *, purchase_price_usd: float, local_regulation: LocalRegulation, market_bundle: MarketBundle
) -> np.ndarray:
    prop13_cap = PROP_13_ANNUAL_CAP ** (market_bundle.month_index.astype("float64") / MONTHS_PER_YEAR)
    assessed_multiplier = np.minimum(market_bundle.inflation_multipliers, prop13_cap[None, :])
    property_tax = (
        purchase_price_usd * (local_regulation.property_tax_annual_pct / 100) * assessed_multiplier / MONTHS_PER_YEAR
    )
    special_assessment = (
        local_regulation.special_assessment_annual_usd / MONTHS_PER_YEAR * market_bundle.inflation_multipliers
    )
    property_tax = property_tax + special_assessment
    property_tax[:, 0] = 0.0
    return np.asarray(property_tax)
