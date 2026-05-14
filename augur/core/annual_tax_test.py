from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.core.annual_tax import annual_sale_tax_allocation, california_income_tax_due_usd, federal_income_tax_due_usd
from augur.core.scenario_set import TaxProfile


def test_federal_ordinary_income_uses_2026_single_brackets_after_standard_deduction() -> None:
    tax = federal_income_tax_due_usd(
        TaxProfile(annual_ordinary_income_usd=100_000),
        ordinary_income_usd=np.asarray([100_000.0]),
        unrecaptured_1250_gain_usd=np.asarray([0.0]),
        long_term_capital_gain_usd=np.asarray([0.0]),
    )

    np.testing.assert_allclose(tax, 13_170)


def test_california_income_uses_2025_single_brackets_after_standard_deduction() -> None:
    tax = california_income_tax_due_usd(
        TaxProfile(annual_ordinary_income_usd=100_000),
        ordinary_income_usd=np.asarray([100_000.0]),
        capital_income_usd=np.asarray([0.0]),
    )

    np.testing.assert_allclose(tax, 5_207.98)


def test_annual_sale_tax_allocates_stock_gain_to_sale_month() -> None:
    shape = (1, 13)
    zeros = np.zeros(shape, dtype="float64")
    stock_gain = zeros.copy()
    stock_gain[:, 5] = 10_000

    allocation = annual_sale_tax_allocation(
        TaxProfile(),
        month_index=np.arange(13, dtype="int64"),
        property_depreciation_recapture_usd=zeros,
        taxable_property_capital_gain_usd=zeros,
        generic_sp500_sale_gain_usd=stock_gain,
        private_equity_sale_taxable_gain_usd=zeros,
    )

    np.testing.assert_allclose(allocation.federal_income_tax_usd[:, 5], 0)
    np.testing.assert_allclose(allocation.california_income_tax_usd[:, 5], 42.94)
    np.testing.assert_allclose(allocation.generic_sp500_sale_tax_usd[:, 5], 42.94)
    np.testing.assert_allclose(allocation.total_income_tax_usd[:, 5], 42.94)
    np.testing.assert_allclose(allocation.total_income_tax_usd[:, :5], 0)
    np.testing.assert_allclose(allocation.total_income_tax_usd[:, 6:], 0)


if __name__ == "__main__":
    pytest_bazel.main()
