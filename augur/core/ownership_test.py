from __future__ import annotations

import numpy as np
import pytest
import pytest_bazel

from augur.core.augur_accounting import resolve_financing
from augur.core.ownership import (
    MonthlyHouseUseComponents,
    OccupantContributionBuildsEquityPolicy,
    apply_occupant_contribution_builds_equity_policy,
)
from augur.core.schemas import KnobsConfig


def base_house_uses(**overrides) -> MonthlyHouseUseComponents:
    values = {
        "mortgage_interest_usd": np.asarray([1000.0, 900.0, 800.0, 700.0]),
        "mortgage_principal_usd": np.asarray([300.0, 400.0, 500.0, 600.0]),
        "property_tax_usd": np.asarray([200.0, 200.0, 200.0, 200.0]),
        "insurance_usd": np.asarray([100.0, 100.0, 100.0, 100.0]),
        "hoa_usd": np.asarray([50.0, 50.0, 50.0, 50.0]),
        "maintenance_usd": np.asarray([150.0, 150.0, 150.0, 150.0]),
    }
    values.update(overrides)
    return MonthlyHouseUseComponents(**values)


def test_allocates_occupied_payment_pro_rata_across_house_uses() -> None:
    components = base_house_uses()
    result = apply_occupant_contribution_builds_equity_policy(
        components,
        OccupantContributionBuildsEquityPolicy(
            base_monthly_payment_usd=900, occupied_months=4, owner_initial_equity_usd=10_000
        ),
    )

    total_month_1 = 1000 + 300 + 200 + 100 + 50 + 150
    expected_share = 900 / total_month_1
    assert result.contribution_share[0] == pytest.approx(expected_share)
    assert result.occupant_interest_usd[0] == pytest.approx(1000 * expected_share)
    assert result.occupant_principal_usd[0] == pytest.approx(300 * expected_share)
    assert result.occupant_property_tax_usd[0] == pytest.approx(200 * expected_share)
    assert result.occupant_insurance_usd[0] == pytest.approx(100 * expected_share)
    assert result.occupant_hoa_usd[0] == pytest.approx(50 * expected_share)
    assert result.occupant_maintenance_usd[0] == pytest.approx(150 * expected_share)
    assert (
        result.occupant_interest_usd[0]
        + result.occupant_principal_usd[0]
        + result.occupant_property_tax_usd[0]
        + result.occupant_insurance_usd[0]
        + result.occupant_hoa_usd[0]
        + result.occupant_maintenance_usd[0]
    ) == pytest.approx(result.contribution_used_usd[0])


def test_caps_payment_at_house_uses_and_tracks_unallocated_excess() -> None:
    result = apply_occupant_contribution_builds_equity_policy(
        base_house_uses(),
        OccupantContributionBuildsEquityPolicy(
            base_monthly_payment_usd=2_500, occupied_months=4, owner_initial_equity_usd=10_000
        ),
    )

    total_month_1 = 1000 + 300 + 200 + 100 + 50 + 150
    assert result.contribution_used_usd[0] == total_month_1
    assert result.unallocated_excess_usd[0] == 2_500 - total_month_1
    assert result.contribution_share[0] == 1


def test_only_occupant_funded_principal_builds_occupant_equity() -> None:
    components = base_house_uses(
        mortgage_interest_usd=np.asarray([100.0, 100.0]),
        mortgage_principal_usd=np.asarray([100.0, 300.0]),
        property_tax_usd=np.asarray([0.0, 0.0]),
        insurance_usd=np.asarray([0.0, 0.0]),
        hoa_usd=np.asarray([0.0, 0.0]),
        maintenance_usd=np.asarray([0.0, 0.0]),
    )
    result = apply_occupant_contribution_builds_equity_policy(
        components,
        OccupantContributionBuildsEquityPolicy(
            base_monthly_payment_usd=100, occupied_months=2, owner_initial_equity_usd=1_000
        ),
    )

    assert result.occupant_principal_usd[0] == pytest.approx(50)
    assert result.occupant_principal_usd[1] == pytest.approx(75)
    np.testing.assert_allclose(result.occupant_equity_ledger_usd, [50, 125])
    np.testing.assert_allclose(result.owner_principal_usd, [50, 225])
    np.testing.assert_allclose(result.owner_equity_ledger_usd, [1050, 1275])
    assert result.occupant_ownership_pct[-1] == pytest.approx(125 / 1400)


def test_freezes_ownership_after_move_out_even_as_owner_keeps_funding_principal() -> None:
    result = apply_occupant_contribution_builds_equity_policy(
        base_house_uses(),
        OccupantContributionBuildsEquityPolicy(
            base_monthly_payment_usd=900,
            occupied_months=3,
            owner_initial_equity_usd=10_000,
            freeze_ownership_after_month=3,
        ),
    )

    assert result.contribution_used_usd[2] > 0
    assert result.contribution_used_usd[3] == 0
    assert result.live_occupant_ownership_pct[3] < result.live_occupant_ownership_pct[2]
    assert result.occupant_ownership_pct[3] == result.occupant_ownership_pct[2]


def test_vectorized_rollout_inputs_keep_independent_equity_ledgers() -> None:
    components = MonthlyHouseUseComponents(
        mortgage_interest_usd=np.asarray([[1000.0, 1000.0], [1000.0, 1000.0]]),
        mortgage_principal_usd=np.asarray([[100.0, 100.0], [200.0, 200.0]]),
        property_tax_usd=0.0,
        insurance_usd=0.0,
        hoa_usd=0.0,
        maintenance_usd=0.0,
    )
    result = apply_occupant_contribution_builds_equity_policy(
        components,
        OccupantContributionBuildsEquityPolicy(
            base_monthly_payment_usd=550, occupied_months=2, owner_initial_equity_usd=1_000
        ),
    )

    assert result.occupant_equity_ledger_usd.shape == (2, 2)
    assert result.contribution_share[0, 0] == pytest.approx(0.5)
    assert result.contribution_share[1, 0] == pytest.approx(550 / 1200)
    assert result.occupant_equity_ledger_usd[0, -1] == pytest.approx(100)
    assert result.occupant_equity_ledger_usd[1, -1] == pytest.approx(200 * 550 / 1200 * 2)


def test_core_financing_matches_vallejo_investment_loan_default() -> None:
    financing = resolve_financing(
        KnobsConfig(
            down_payment_pct=25,
            credit_score=776,
            custom_mortgage_rate=6.5,
            custom_mortgage_term_years=20,
            starting_portfolio_usd=0,
            custom_counterfactual_rent_monthly_usd=0,
            counterfactual_rent_growth=3,
            hold_years=5,
            appreciation_rate=2,
            sp500_rate=7,
            maintenance_pct=1,
            owner_occupancy_years=0,
            marginal_tax_rate=40,
            cap_gains_rate=30,
            inflation=3,
            vacancy_pct=5,
            mgmt_pct=8,
            leasing_fee_pct=0,
            rooms_rented_while_living=0,
            room_rent_monthly_usd=0,
            room_vacancy_pct=0,
            portfolio_liquidation_tax_pct=0,
            insurance_annual_usd=1800,
            closing_cost_buy_pct=2.5,
            closing_cost_sell_pct=6.5,
            cap_gains_exclusion_usd=250_000,
            depreciable_basis_pct=80,
            financing_mode="fixed_30",
            occupancy_type="investment",
            rent_counterfactual_mode="custom",
        )
    )

    assert financing.term_years == 30
    assert financing.rate_pct == pytest.approx(6.83)
    assert financing.loan_to_value_pct == 75


if __name__ == "__main__":
    pytest_bazel.main()
