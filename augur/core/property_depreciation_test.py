from __future__ import annotations

import numpy as np
import pytest_bazel

from augur.core.market_bundle_test_support import constant_market_bundle
from augur.core.property_depreciation import monthly_property_depreciation_usd, rental_active_mask
from augur.core.scenario_set import (
    Actor,
    ActorRole,
    OccupancyPlan,
    PropertyAssumptions,
    RentalMode,
    RentalPlan,
    Scenario,
)


def scenario_with_rental_plan(rental_plan: RentalPlan) -> Scenario:
    return Scenario(
        scenario_id="rental",
        label="Rental",
        actors=(Actor(actor_id="owner", label="Owner", role=ActorRole.PRIMARY_OWNER),),
        rental_plan=rental_plan,
        property_assumptions=PropertyAssumptions(depreciable_basis_pct=100),
    )


def test_rental_active_mask_starts_after_occupancy_for_transition_rental() -> None:
    scenario = Scenario(
        scenario_id="transition",
        label="Transition",
        actors=(Actor(actor_id="owner", label="Owner", role=ActorRole.PRIMARY_OWNER),),
        occupancy_plan=OccupancyPlan(end_month=2),
        rental_plan=RentalPlan(rental_mode=RentalMode.TRANSITION_TO_WHOLE_PROPERTY_RENTAL, monthly_rent_usd=2_000),
    )

    np.testing.assert_array_equal(
        rental_active_mask(scenario, constant_market_bundle(horizon_months=5)),
        np.asarray([False, False, False, True, True, True]),
    )


def test_depreciation_only_applies_during_active_rental_months_before_sale() -> None:
    depreciation = monthly_property_depreciation_usd(
        scenario_with_rental_plan(
            RentalPlan(rental_mode=RentalMode.RENT_WHOLE_PROPERTY, start_month=2, end_month=4, monthly_rent_usd=2_000)
        ),
        constant_market_bundle(horizon_months=6),
        purchase_price_usd=330_000,
        purchase_closing_cost_usd=0,
        sale_month=3,
    )

    expected_monthly = 330_000 / (27.5 * 12)
    np.testing.assert_allclose(depreciation[:, :2], 0)
    np.testing.assert_allclose(depreciation[:, 2:4], expected_monthly)
    np.testing.assert_allclose(depreciation[:, 4:], 0)


if __name__ == "__main__":
    pytest_bazel.main()
