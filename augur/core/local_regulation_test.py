from __future__ import annotations

import numpy as np
import pytest
import pytest_bazel
from pydantic import ValidationError

from augur.core.local_regulation import (
    LocationId,
    TaxRegime,
    _validate_local_regulation_data,
    known_location_id,
    local_regulation_for_location,
    tax_regimes_for_local_regulation,
)
from augur.core.market_bundle_test_support import constant_market_bundle
from augur.core.property_tax import monthly_property_tax_usd


def _valid_payload() -> dict[str, dict[str, dict[str, object]]]:
    return {
        "local_regulation_by_location": {
            location_id.value: {
                "property_tax_regime": "san_francisco_secured_property_tax",
                "default_tax_regimes": [
                    "california_prop13",
                    "federal_mortgage_interest",
                    "san_francisco_secured_property_tax",
                ],
                "property_tax_annual_pct": 1.0,
                "local_transfer_tax_pct": 0.0,
                "special_assessment_annual_usd": 0.0,
                "notes": f"{location_id.value} test fixture",
            }
            for location_id in LocationId
        }
    }


def test_unknown_location_rejected() -> None:
    assert known_location_id("oakland_ca") is None
    with pytest.raises(ValueError, match="unknown built-in local regulation"):
        local_regulation_for_location("oakland_ca")


def test_loaded_builtin_regulation_drives_property_tax() -> None:
    regulation = local_regulation_for_location(LocationId.MARE_ISLAND_VALLEJO_CA)

    taxes = monthly_property_tax_usd(
        purchase_price_usd=100_000,
        local_regulation=regulation,
        market_bundle=constant_market_bundle(inflation_path=(1.0, 1.0)),
    )

    np.testing.assert_allclose(taxes[:, 0], 0.0)
    np.testing.assert_allclose(taxes[:, 1], 100_000 * 0.024 / 12)


def test_loaded_builtin_regulation_drives_tax_regime_defaults() -> None:
    regulation = local_regulation_for_location(LocationId.SAN_FRANCISCO_CA)

    regimes = tax_regimes_for_local_regulation(regulation, owner_occupied=True, rented=True)

    assert regulation.property_tax_regime is TaxRegime.SAN_FRANCISCO_SECURED_PROPERTY_TAX
    assert TaxRegime.SAN_FRANCISCO_TRANSFER_TAX in regimes
    assert TaxRegime.PRIMARY_RESIDENCE_EXCLUSION in regimes
    assert TaxRegime.RENTAL_DEPRECIATION in regimes


def test_local_regulation_data_requires_all_builtin_locations() -> None:
    payload = _valid_payload()
    table = dict(payload["local_regulation_by_location"])
    del table[LocationId.MARE_ISLAND_VALLEJO_CA.value]
    payload["local_regulation_by_location"] = table

    with pytest.raises(ValidationError, match="missing: mare_island_vallejo_ca"):
        _validate_local_regulation_data(payload)


def test_local_regulation_data_requires_regulation_fields() -> None:
    payload = _valid_payload()
    table = dict(payload["local_regulation_by_location"])
    san_francisco = dict(table[LocationId.SAN_FRANCISCO_CA.value])
    del san_francisco["notes"]
    table[LocationId.SAN_FRANCISCO_CA.value] = san_francisco
    payload["local_regulation_by_location"] = table

    with pytest.raises(ValidationError, match="notes"):
        _validate_local_regulation_data(payload)


def test_local_regulation_data_requires_tax_regime_fields() -> None:
    payload = _valid_payload()
    table = dict(payload["local_regulation_by_location"])
    san_francisco = dict(table[LocationId.SAN_FRANCISCO_CA.value])
    del san_francisco["property_tax_regime"]
    table[LocationId.SAN_FRANCISCO_CA.value] = san_francisco
    payload["local_regulation_by_location"] = table

    with pytest.raises(ValidationError, match="property_tax_regime"):
        _validate_local_regulation_data(payload)


if __name__ == "__main__":
    pytest_bazel.main()
