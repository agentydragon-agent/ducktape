from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.core.local_regulation import LocalRegulation, TaxRegime
from augur.core.market_bundle_test_support import constant_market_bundle
from augur.core.property_tax import monthly_property_tax_usd


def _local_regulation(**overrides: object) -> LocalRegulation:
    values = {
        "property_tax_regime": TaxRegime.CALIFORNIA_PROP13,
        "default_tax_regimes": (TaxRegime.CALIFORNIA_PROP13,),
        "property_tax_annual_pct": 1.2,
        "notes": "test",
    }
    values.update(overrides)
    return LocalRegulation(**values)


def test_monthly_property_tax_uses_prop13_assessed_value_cap() -> None:
    taxes = monthly_property_tax_usd(
        purchase_price_usd=1_200_000,
        local_regulation=_local_regulation(),
        market_bundle=constant_market_bundle(
            horizon_months=12,
            inflation_path=(1.0, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07, 1.08, 1.09, 1.10, 1.11, 1.12),
        ),
    )

    expected_uncapped = 1_200_000 * 0.012 * 1.12 / 12
    expected_capped = 1_200_000 * 0.012 * 1.02 / 12
    np.testing.assert_allclose(taxes[:, 0], 0)
    assert taxes[0, 12] < expected_uncapped
    np.testing.assert_allclose(taxes[:, 12], expected_capped)


def test_monthly_property_tax_adds_special_assessment_with_inflation() -> None:
    taxes = monthly_property_tax_usd(
        purchase_price_usd=100_000,
        local_regulation=_local_regulation(special_assessment_annual_usd=1_200),
        market_bundle=constant_market_bundle(inflation_path=(1.0, 1.0, 1.1, 1.2)),
    )

    np.testing.assert_allclose(taxes[:, 0], 0)
    np.testing.assert_allclose(taxes[:, 1], 100_000 * 0.012 / 12 + 100)
    expected_assessed_multiplier = 1.02 ** (3 / 12)
    np.testing.assert_allclose(taxes[:, 3], 100_000 * 0.012 / 12 * expected_assessed_multiplier + 120)


if __name__ == "__main__":
    pytest_bazel.main()
