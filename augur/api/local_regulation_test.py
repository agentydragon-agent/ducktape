from __future__ import annotations

import pytest_bazel

from augur.api.local_regulation import LocalRegulation, TaxRegime, tax_regimes_for_local_regulation


def _san_francisco_regulation() -> LocalRegulation:
    return LocalRegulation(
        property_tax_regime=TaxRegime.SAN_FRANCISCO_SECURED_PROPERTY_TAX,
        default_tax_regimes=(
            TaxRegime.CALIFORNIA_PROP13,
            TaxRegime.CALIFORNIA_TRANSFER_TAX,
            TaxRegime.FEDERAL_MORTGAGE_INTEREST,
            TaxRegime.FEDERAL_CAPITAL_GAINS,
            TaxRegime.CALIFORNIA_INCOME_TAX,
            TaxRegime.SAN_FRANCISCO_SECURED_PROPERTY_TAX,
            TaxRegime.SAN_FRANCISCO_TRANSFER_TAX,
        ),
        property_tax_annual_pct=1.18,
        notes="San Francisco fixture",
    )


def test_owner_occupied_with_rooms_rented_keeps_owner_occupied_treatment() -> None:
    regulation = _san_francisco_regulation()

    regimes = tax_regimes_for_local_regulation(regulation, owner_occupied=True, rented=True)

    assert regulation.property_tax_regime is TaxRegime.SAN_FRANCISCO_SECURED_PROPERTY_TAX
    assert TaxRegime.SAN_FRANCISCO_TRANSFER_TAX in regimes
    assert TaxRegime.PRIMARY_RESIDENCE_EXCLUSION in regimes
    assert TaxRegime.RENTAL_DEPRECIATION in regimes
    assert TaxRegime.CALIFORNIA_OWNER_OCCUPIED in regimes


def test_investment_property_treatment_when_owner_does_not_occupy() -> None:
    regulation = _san_francisco_regulation()

    regimes = tax_regimes_for_local_regulation(regulation, owner_occupied=False, rented=True)

    assert TaxRegime.CALIFORNIA_INVESTMENT_PROPERTY in regimes
    assert TaxRegime.PRIMARY_RESIDENCE_EXCLUSION not in regimes
    assert TaxRegime.RENTAL_DEPRECIATION in regimes


def test_existing_tax_regimes_are_preserved_and_deduplicated() -> None:
    regulation = _san_francisco_regulation()

    regimes = tax_regimes_for_local_regulation(
        regulation,
        owner_occupied=True,
        rented=False,
        existing_tax_regimes=(TaxRegime.CALIFORNIA_PROP13, TaxRegime.MARE_ISLAND_SPECIAL_ASSESSMENTS),
    )

    assert TaxRegime.MARE_ISLAND_SPECIAL_ASSESSMENTS in regimes
    assert regimes.count(TaxRegime.CALIFORNIA_PROP13) == 1


if __name__ == "__main__":
    pytest_bazel.main()
