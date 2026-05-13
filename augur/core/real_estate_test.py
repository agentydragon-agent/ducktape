from __future__ import annotations

import numpy as np
import pytest
import pytest_bazel

from augur.core.ownership import OccupantContributionBuildsEquityPolicy
from augur.core.real_estate import simulate_real_estate_case
from augur.core.schemas import PropertyRequest, ScenarioKnobs
from augur.core.vectorized import deterministic_market_paths


def base_knobs(**overrides) -> ScenarioKnobs:
    values: dict[str, object] = {
        "down_payment_pct": 25,
        "credit_score": 776,
        "custom_mortgage_rate": 6.5,
        "custom_mortgage_term_years": 20,
        "starting_portfolio_usd": 750_000,
        "custom_counterfactual_rent_monthly_usd": 2_800,
        "counterfactual_rent_growth": 3,
        "hold_years": 10,
        "appreciation_rate": 2,
        "sp500_rate": 7,
        "maintenance_pct": 1,
        "owner_occupancy_years": 3,
        "marginal_tax_rate": 40,
        "cap_gains_rate": 30,
        "inflation": 3,
        "vacancy_pct": 5,
        "mgmt_pct": 8,
        "leasing_fee_pct": 0,
        "rooms_rented_while_living": 0,
        "room_rent_monthly_usd": 0,
        "room_vacancy_pct": 0,
        "portfolio_liquidation_tax_pct": 0,
        "insurance_annual_usd": 1_800,
        "closing_cost_buy_pct": 2.5,
        "closing_cost_sell_pct": 6.5,
        "cap_gains_exclusion_usd": 250_000,
        "depreciable_basis_pct": 80,
        "financing_mode": "fixed_30",
        "occupancy_type": "investment",
        "rent_counterfactual_mode": "custom",
    }
    values.update(overrides)
    return ScenarioKnobs.model_validate(values)


def sf_property() -> PropertyRequest:
    return PropertyRequest(
        id="sf",
        price_usd=900_000,
        beds=3,
        hoa_monthly_usd=250,
        rent_zestimate_usd=4_000,
        tax_rate_override=0.0118268325,
    )


def vallejo_property() -> PropertyRequest:
    return PropertyRequest(
        id="madrone", price_usd=739_000, beds=4, hoa_monthly_usd=0, rent_zestimate_usd=3_786, tax_rate_override=0.024
    )


def partner_policy(knobs: ScenarioKnobs) -> OccupantContributionBuildsEquityPolicy:
    occupied_months = int(knobs.owner_occupancy_years * 12)
    return OccupantContributionBuildsEquityPolicy(
        owner_actor="owner",
        occupant_actor="occupant",
        base_monthly_payment_usd=2_435,
        payment_growth_annual_pct=knobs.inflation,
        occupied_months=occupied_months,
        freeze_ownership_after_month=occupied_months,
    )


def test_sf_case_without_occupant_policy_keeps_one_owner_sale_claim() -> None:
    result = simulate_real_estate_case(sf_property(), base_knobs())

    assert result.ownership is None
    assert result.owner_actor == "owner"
    assert result.occupant_actor is None
    np.testing.assert_allclose(result.owner_ownership_pct, [1])
    np.testing.assert_allclose(result.occupant_ownership_pct, [0])
    np.testing.assert_allclose(result.owner_sale_claim_usd, result.simulation.sale_net_proceeds_usd[:, -1])
    np.testing.assert_allclose(result.occupant_sale_claim_usd, [0])


def test_vallejo_case_uses_same_simulator_with_partner_ownership_policy() -> None:
    knobs = base_knobs()
    result = simulate_real_estate_case(vallejo_property(), knobs, ownership_policy=partner_policy(knobs))

    assert result.simulation.tax_rate == 0.024
    assert result.simulation.financing.rate_pct == pytest.approx(6.83)
    assert result.ownership is not None
    assert result.owner_actor == "owner"
    assert result.occupant_actor == "occupant"
    assert result.occupant_ownership_pct[0] > 0
    assert result.occupant_ownership_pct[0] < 1
    np.testing.assert_allclose(
        result.owner_sale_claim_usd + result.occupant_sale_claim_usd, result.simulation.sale_net_proceeds_usd[:, -1]
    )

    freeze_index = int(knobs.owner_occupancy_years * 12) - 1
    np.testing.assert_allclose(
        result.ownership.occupant_ownership_pct[0, freeze_index:],
        result.ownership.occupant_ownership_pct[0, freeze_index],
    )


def test_vectorized_case_splits_sale_claims_across_rollouts() -> None:
    knobs = base_knobs()
    paths = deterministic_market_paths(knobs, hold_months=int(knobs.hold_years) * 12, rollout_count=3)
    paths.sale_home_value_multipliers[:, -1] = np.asarray([0.9, 1.0, 1.2])
    result = simulate_real_estate_case(vallejo_property(), knobs, paths, ownership_policy=partner_policy(knobs))

    assert result.ownership is not None
    assert result.occupant_sale_claim_usd.shape == (3,)
    assert result.ownership.occupant_ownership_pct.shape == (3, int(knobs.hold_years) * 12)
    np.testing.assert_allclose(
        result.owner_sale_claim_usd + result.occupant_sale_claim_usd, result.simulation.sale_net_proceeds_usd[:, -1]
    )
    assert result.occupant_sale_claim_usd[0] < result.occupant_sale_claim_usd[-1]


if __name__ == "__main__":
    pytest_bazel.main()
