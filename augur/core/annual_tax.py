from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from augur.core.scenario_set import TaxFilingStatus, TaxProfile

Bracket = tuple[float | None, float]

FEDERAL_STANDARD_DEDUCTION_2026 = {
    TaxFilingStatus.SINGLE: 16_100.0,
    TaxFilingStatus.MARRIED_FILING_JOINTLY: 32_200.0,
    TaxFilingStatus.MARRIED_FILING_SEPARATELY: 16_100.0,
    TaxFilingStatus.HEAD_OF_HOUSEHOLD: 24_150.0,
}

FEDERAL_ORDINARY_BRACKETS_2026: dict[TaxFilingStatus, tuple[Bracket, ...]] = {
    TaxFilingStatus.SINGLE: (
        (12_400.0, 0.10),
        (50_400.0, 0.12),
        (105_700.0, 0.22),
        (201_775.0, 0.24),
        (256_225.0, 0.32),
        (640_600.0, 0.35),
        (None, 0.37),
    ),
    TaxFilingStatus.MARRIED_FILING_JOINTLY: (
        (24_800.0, 0.10),
        (100_800.0, 0.12),
        (211_400.0, 0.22),
        (403_550.0, 0.24),
        (512_450.0, 0.32),
        (768_700.0, 0.35),
        (None, 0.37),
    ),
    TaxFilingStatus.MARRIED_FILING_SEPARATELY: (
        (12_400.0, 0.10),
        (50_400.0, 0.12),
        (105_700.0, 0.22),
        (201_775.0, 0.24),
        (256_225.0, 0.32),
        (384_350.0, 0.35),
        (None, 0.37),
    ),
    TaxFilingStatus.HEAD_OF_HOUSEHOLD: (
        (17_700.0, 0.10),
        (67_450.0, 0.12),
        (105_700.0, 0.22),
        (201_750.0, 0.24),
        (256_200.0, 0.32),
        (640_600.0, 0.35),
        (None, 0.37),
    ),
}

FEDERAL_LONG_TERM_CAPITAL_GAIN_THRESHOLDS_2026 = {
    TaxFilingStatus.SINGLE: (49_450.0, 545_500.0),
    TaxFilingStatus.MARRIED_FILING_JOINTLY: (98_900.0, 613_700.0),
    TaxFilingStatus.MARRIED_FILING_SEPARATELY: (49_450.0, 306_850.0),
    TaxFilingStatus.HEAD_OF_HOUSEHOLD: (66_200.0, 579_600.0),
}

CALIFORNIA_STANDARD_DEDUCTION_2025 = {
    TaxFilingStatus.SINGLE: 5_706.0,
    TaxFilingStatus.MARRIED_FILING_JOINTLY: 11_412.0,
    TaxFilingStatus.MARRIED_FILING_SEPARATELY: 5_706.0,
    TaxFilingStatus.HEAD_OF_HOUSEHOLD: 11_412.0,
}

CALIFORNIA_ORDINARY_BRACKETS_2025: dict[TaxFilingStatus, tuple[Bracket, ...]] = {
    TaxFilingStatus.SINGLE: (
        (11_079.0, 0.01),
        (26_264.0, 0.02),
        (41_452.0, 0.04),
        (57_542.0, 0.06),
        (72_724.0, 0.08),
        (371_479.0, 0.093),
        (445_771.0, 0.103),
        (742_953.0, 0.113),
        (None, 0.123),
    ),
    TaxFilingStatus.MARRIED_FILING_JOINTLY: (
        (22_158.0, 0.01),
        (52_528.0, 0.02),
        (82_904.0, 0.04),
        (115_084.0, 0.06),
        (145_448.0, 0.08),
        (742_958.0, 0.093),
        (891_542.0, 0.103),
        (1_485_906.0, 0.113),
        (None, 0.123),
    ),
    TaxFilingStatus.MARRIED_FILING_SEPARATELY: (
        (11_079.0, 0.01),
        (26_264.0, 0.02),
        (41_452.0, 0.04),
        (57_542.0, 0.06),
        (72_724.0, 0.08),
        (371_479.0, 0.093),
        (445_771.0, 0.103),
        (742_953.0, 0.113),
        (None, 0.123),
    ),
    TaxFilingStatus.HEAD_OF_HOUSEHOLD: (
        (22_173.0, 0.01),
        (52_530.0, 0.02),
        (67_716.0, 0.04),
        (83_805.0, 0.06),
        (98_990.0, 0.08),
        (505_208.0, 0.093),
        (606_251.0, 0.103),
        (1_010_417.0, 0.113),
        (None, 0.123),
    ),
}

CALIFORNIA_BEHAVIORAL_HEALTH_SERVICES_TAX_THRESHOLD_USD = 1_000_000.0
CALIFORNIA_BEHAVIORAL_HEALTH_SERVICES_TAX_RATE = 0.01
FEDERAL_UNRECAPTURED_1250_GAIN_MAX_RATE = 0.25


@dataclass(frozen=True)
class AnnualSaleTaxAllocation:
    federal_income_tax_usd: np.ndarray
    california_income_tax_usd: np.ndarray
    total_income_tax_usd: np.ndarray
    property_sale_tax_usd: np.ndarray
    generic_sp500_sale_tax_usd: np.ndarray
    private_equity_sale_tax_usd: np.ndarray


def annual_sale_tax_allocation(
    tax_profile: TaxProfile,
    *,
    month_index: np.ndarray,
    property_depreciation_recapture_usd: np.ndarray,
    taxable_property_capital_gain_usd: np.ndarray,
    generic_sp500_sale_gain_usd: np.ndarray,
    private_equity_sale_taxable_gain_usd: np.ndarray,
) -> AnnualSaleTaxAllocation:
    """Allocate annual federal and California tax created by simulated sale gains.

    This computes the incremental yearly tax over the scenario's baseline
    ordinary income, then allocates that tax back to the sale months and sources
    that generated the taxable income.
    """
    source_shape = property_depreciation_recapture_usd.shape
    federal_income_tax = np.zeros(source_shape, dtype="float64")
    california_income_tax = np.zeros(source_shape, dtype="float64")
    property_sale_tax = np.zeros(source_shape, dtype="float64")
    generic_sp500_sale_tax = np.zeros(source_shape, dtype="float64")
    private_equity_sale_tax = np.zeros(source_shape, dtype="float64")

    property_recapture = np.maximum(0.0, property_depreciation_recapture_usd)
    property_capital_gain = np.maximum(0.0, taxable_property_capital_gain_usd)
    sp500_capital_gain = np.maximum(0.0, generic_sp500_sale_gain_usd)
    private_equity_capital_gain = np.maximum(0.0, private_equity_sale_taxable_gain_usd)
    property_taxable_income = property_recapture + property_capital_gain
    total_taxable_income = property_taxable_income + sp500_capital_gain + private_equity_capital_gain

    rollout_count = source_shape[0]
    ordinary_income = np.full(rollout_count, float(tax_profile.annual_ordinary_income_usd), dtype="float64")
    baseline_federal = federal_income_tax_due_usd(
        tax_profile,
        ordinary_income_usd=ordinary_income,
        unrecaptured_1250_gain_usd=np.zeros(rollout_count, dtype="float64"),
        long_term_capital_gain_usd=np.zeros(rollout_count, dtype="float64"),
    )
    baseline_california = california_income_tax_due_usd(
        tax_profile, ordinary_income_usd=ordinary_income, capital_income_usd=np.zeros(rollout_count, dtype="float64")
    )

    for tax_year in np.unique(month_index // 12):
        year_mask = (month_index // 12) == tax_year
        year_property_recapture = np.sum(property_recapture[:, year_mask], axis=1)
        year_property_capital_gain = np.sum(property_capital_gain[:, year_mask], axis=1)
        year_sp500_capital_gain = np.sum(sp500_capital_gain[:, year_mask], axis=1)
        year_private_equity_capital_gain = np.sum(private_equity_capital_gain[:, year_mask], axis=1)
        year_long_term_capital_gain = (
            year_property_capital_gain + year_sp500_capital_gain + year_private_equity_capital_gain
        )
        year_taxable_income = np.sum(total_taxable_income[:, year_mask], axis=1)

        year_federal_tax = np.maximum(
            0.0,
            federal_income_tax_due_usd(
                tax_profile,
                ordinary_income_usd=ordinary_income,
                unrecaptured_1250_gain_usd=year_property_recapture,
                long_term_capital_gain_usd=year_long_term_capital_gain,
            )
            - baseline_federal,
        )
        year_california_tax = np.maximum(
            0.0,
            california_income_tax_due_usd(
                tax_profile,
                ordinary_income_usd=ordinary_income,
                capital_income_usd=year_property_recapture + year_long_term_capital_gain,
            )
            - baseline_california,
        )
        year_total_tax = year_federal_tax + year_california_tax

        federal_income_tax[:, year_mask] = _allocate_tax_to_months(
            year_federal_tax, total_taxable_income[:, year_mask], year_taxable_income
        )
        california_income_tax[:, year_mask] = _allocate_tax_to_months(
            year_california_tax, total_taxable_income[:, year_mask], year_taxable_income
        )
        property_sale_tax[:, year_mask] = _allocate_tax_to_months(
            year_total_tax, property_taxable_income[:, year_mask], year_taxable_income
        )
        generic_sp500_sale_tax[:, year_mask] = _allocate_tax_to_months(
            year_total_tax, sp500_capital_gain[:, year_mask], year_taxable_income
        )
        private_equity_sale_tax[:, year_mask] = _allocate_tax_to_months(
            year_total_tax, private_equity_capital_gain[:, year_mask], year_taxable_income
        )

    return AnnualSaleTaxAllocation(
        federal_income_tax_usd=federal_income_tax,
        california_income_tax_usd=california_income_tax,
        total_income_tax_usd=federal_income_tax + california_income_tax,
        property_sale_tax_usd=property_sale_tax,
        generic_sp500_sale_tax_usd=generic_sp500_sale_tax,
        private_equity_sale_tax_usd=private_equity_sale_tax,
    )


def federal_income_tax_due_usd(
    tax_profile: TaxProfile,
    *,
    ordinary_income_usd: np.ndarray,
    unrecaptured_1250_gain_usd: np.ndarray,
    long_term_capital_gain_usd: np.ndarray,
) -> np.ndarray:
    filing_status = tax_profile.filing_status
    standard_deduction = _federal_standard_deduction(tax_profile)
    ordinary_income = np.maximum(0.0, ordinary_income_usd)
    recapture_gain = np.maximum(0.0, unrecaptured_1250_gain_usd)
    long_term_capital_gain = np.maximum(0.0, long_term_capital_gain_usd)

    ordinary_taxable_income = np.maximum(0.0, ordinary_income - standard_deduction)
    deduction_after_ordinary = np.maximum(0.0, standard_deduction - ordinary_income)
    recapture_taxable_income = np.maximum(0.0, recapture_gain - deduction_after_ordinary)
    deduction_after_recapture = np.maximum(0.0, deduction_after_ordinary - recapture_gain)
    long_term_capital_gain_taxable = np.maximum(0.0, long_term_capital_gain - deduction_after_recapture)

    ordinary_tax = _progressive_tax(ordinary_taxable_income, FEDERAL_ORDINARY_BRACKETS_2026[filing_status])
    recapture_as_ordinary_tax = (
        _progressive_tax(
            ordinary_taxable_income + recapture_taxable_income, FEDERAL_ORDINARY_BRACKETS_2026[filing_status]
        )
        - ordinary_tax
    )
    recapture_tax = np.minimum(
        recapture_as_ordinary_tax, recapture_taxable_income * FEDERAL_UNRECAPTURED_1250_GAIN_MAX_RATE
    )
    long_term_capital_gain_tax = _federal_long_term_capital_gain_tax(
        filing_status, ordinary_taxable_income + recapture_taxable_income, long_term_capital_gain_taxable
    )
    total_tax = ordinary_tax.copy()
    total_tax += recapture_tax
    total_tax += long_term_capital_gain_tax
    return total_tax


def california_income_tax_due_usd(
    tax_profile: TaxProfile, *, ordinary_income_usd: np.ndarray, capital_income_usd: np.ndarray
) -> np.ndarray:
    filing_status = tax_profile.filing_status
    taxable_income = np.maximum(
        0.0,
        np.maximum(0.0, ordinary_income_usd)
        + np.maximum(0.0, capital_income_usd)
        - _california_standard_deduction(tax_profile),
    )
    ordinary_tax = _progressive_tax(taxable_income, CALIFORNIA_ORDINARY_BRACKETS_2025[filing_status])
    behavioral_health_services_tax = (
        np.maximum(0.0, taxable_income - CALIFORNIA_BEHAVIORAL_HEALTH_SERVICES_TAX_THRESHOLD_USD)
        * CALIFORNIA_BEHAVIORAL_HEALTH_SERVICES_TAX_RATE
    )
    total_tax = ordinary_tax.copy()
    total_tax += behavioral_health_services_tax
    return total_tax


def _federal_standard_deduction(tax_profile: TaxProfile) -> float:
    if tax_profile.federal_standard_deduction_usd is not None:
        return float(tax_profile.federal_standard_deduction_usd)
    return FEDERAL_STANDARD_DEDUCTION_2026[tax_profile.filing_status]


def _california_standard_deduction(tax_profile: TaxProfile) -> float:
    if tax_profile.california_standard_deduction_usd is not None:
        return float(tax_profile.california_standard_deduction_usd)
    return CALIFORNIA_STANDARD_DEDUCTION_2025[tax_profile.filing_status]


def _federal_long_term_capital_gain_tax(
    filing_status: TaxFilingStatus, ordinary_taxable_income_usd: np.ndarray, gain_usd: np.ndarray
) -> np.ndarray:
    zero_rate_ceiling, fifteen_rate_ceiling = FEDERAL_LONG_TERM_CAPITAL_GAIN_THRESHOLDS_2026[filing_status]
    gain = np.maximum(0.0, gain_usd)
    zero_rate_room = np.maximum(0.0, zero_rate_ceiling - ordinary_taxable_income_usd)
    zero_rate_gain = np.minimum(gain, zero_rate_room)
    remaining_gain = np.maximum(0.0, gain - zero_rate_gain)
    fifteen_rate_room = np.maximum(
        0.0, fifteen_rate_ceiling - np.maximum(ordinary_taxable_income_usd, zero_rate_ceiling)
    )
    fifteen_rate_gain = np.minimum(remaining_gain, fifteen_rate_room)
    twenty_rate_gain = np.maximum(0.0, remaining_gain - fifteen_rate_gain)
    tax = np.zeros_like(gain, dtype="float64")
    tax += fifteen_rate_gain * 0.15
    tax += twenty_rate_gain * 0.20
    return tax


def _progressive_tax(income_usd: np.ndarray, brackets: tuple[Bracket, ...]) -> np.ndarray:
    income = np.maximum(0.0, income_usd)
    tax = np.zeros_like(income, dtype="float64")
    lower_bound = 0.0
    for upper_bound, rate in brackets:
        if upper_bound is None:
            bracket_income = np.maximum(0.0, income - lower_bound)
        else:
            bracket_income = np.minimum(np.maximum(0.0, income - lower_bound), upper_bound - lower_bound)
            lower_bound = upper_bound
        tax = tax + bracket_income * rate
    return tax


def _allocate_tax_to_months(
    tax_usd: np.ndarray, monthly_source_usd: np.ndarray, year_source_usd: np.ndarray
) -> np.ndarray:
    allocated_tax = np.zeros_like(monthly_source_usd, dtype="float64")
    np.divide(
        tax_usd[:, None] * monthly_source_usd,
        year_source_usd[:, None],
        out=allocated_tax,
        where=year_source_usd[:, None] > 0,
    )
    return allocated_tax
