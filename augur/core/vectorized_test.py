from __future__ import annotations

import numpy as np
import pytest
import pytest_bazel

from augur.core.augur_accounting import project_monthly_sale_path, simulate_arrangement
from augur.core.schemas import PropertyRequest, ScenarioKnobs
from augur.core.vectorized import (
    CheckingFloorPolicy,
    apply_checking_floor_policy,
    array_columns,
    array_table,
    columnar_table_from_rows,
    deterministic_market_paths,
    simulate_property_vectorized,
)


def base_property() -> PropertyRequest:
    return PropertyRequest(id="test-home", price_usd=900_000, beds=3, hoa_monthly_usd=250, rent_zestimate_usd=4_000)


def base_knobs(**overrides) -> ScenarioKnobs:
    values: dict[str, object] = {
        "down_payment_pct": 30,
        "credit_score": 776,
        "custom_mortgage_rate": 6.5,
        "custom_mortgage_term_years": 20,
        "starting_portfolio_usd": 1_000_000,
        "hold_years": 10,
        "appreciation_rate": 2.5,
        "sp500_rate": 7,
        "maintenance_pct": 1,
        "owner_occupancy_years": 3,
        "marginal_tax_rate": 40,
        "cap_gains_rate": 30,
        "inflation": 3,
        "vacancy_pct": 5,
        "mgmt_pct": 8,
        "leasing_fee_pct": 50,
        "rooms_rented_while_living": 0,
        "room_rent_monthly_usd": 1_800,
        "room_vacancy_pct": 8,
        "portfolio_liquidation_tax_pct": 0,
        "insurance_annual_usd": 2_400,
        "closing_cost_buy_pct": 2.5,
        "closing_cost_sell_pct": 6.5,
        "cap_gains_exclusion_usd": 250_000,
        "depreciable_basis_pct": 80,
        "financing_mode": "fixed_30",
        "occupancy_type": "primary_residence",
    }
    values.update(overrides)
    return ScenarioKnobs.model_validate(values)


def test_non_snake_case_enum_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="financing_mode"):
        base_knobs(financing_mode="fixed15")
    with pytest.raises(ValueError, match="occupancy_type"):
        base_knobs(occupancy_type="primaryResidence")


def test_single_rollout_matches_scalar_terminal_sale_path() -> None:
    property_ = base_property()
    knobs = base_knobs()
    scalar = simulate_arrangement(property_, knobs)
    scalar_sale_path = project_monthly_sale_path(scalar)
    paths = deterministic_market_paths(knobs, hold_months=int(knobs.hold_years) * 12)
    vectorized = simulate_property_vectorized(property_, knobs, paths)
    terminal_month = int(knobs.hold_years) * 12
    terminal_scalar = scalar_sale_path[terminal_month]

    assert abs(vectorized.sale_net_proceeds_usd[0, terminal_month] - terminal_scalar.net_sale_proceeds_usd) < 1.0
    assert abs(vectorized.buy_liquid_usd[0, terminal_month] - terminal_scalar.buy_liquid_usd) < 1.0
    assert abs(vectorized.buy_path_usd[0, terminal_month] - terminal_scalar.buy_path_usd) < 1.0


def test_multi_rollout_outputs_are_array_shaped_and_finite() -> None:
    property_ = base_property()
    knobs = base_knobs()
    paths = deterministic_market_paths(knobs, hold_months=int(knobs.hold_years) * 12, rollout_count=4)
    paths.home_value_multipliers[:, -1] = np.array([0.8, 1.0, 1.2, 1.5])
    paths.sale_home_value_multipliers[:, -1] = np.array([0.8, 1.0, 1.2, 1.5])
    vectorized = simulate_property_vectorized(property_, knobs, paths)

    assert vectorized.home_value_usd.shape == (4, 121)
    assert vectorized.buy_path_usd.shape == (4, 121)
    assert np.all(np.isfinite(vectorized.buy_path_usd))
    assert vectorized.buy_path_usd[0, -1] < vectorized.buy_path_usd[-1, -1]


def test_array_columns_exports_snake_case_columnar_arrays_for_js() -> None:
    property_ = base_property()
    knobs = base_knobs()
    paths = deterministic_market_paths(knobs, hold_months=int(knobs.hold_years) * 12, rollout_count=2)
    vectorized = simulate_property_vectorized(property_, knobs, paths)

    all_rollouts = array_columns(vectorized)
    one_rollout = array_columns(vectorized, rollout_index=1)

    assert len(all_rollouts["buy_path_usd"]) == 2
    assert len(all_rollouts["buy_path_usd"][0]) == 121
    assert len(one_rollout["buy_path_usd"]) == 121
    assert "buy_liquid_usd" in one_rollout


def test_array_table_exports_first_class_columnar_payload() -> None:
    property_ = base_property()
    knobs = base_knobs()
    paths = deterministic_market_paths(knobs, hold_months=int(knobs.hold_years) * 12, rollout_count=2)
    vectorized = simulate_property_vectorized(property_, knobs, paths)

    table = array_table(vectorized, rollout_index=1)

    assert table.row_count == 121
    assert table.columns["buy_path_usd"][-1] == pytest.approx(vectorized.buy_path_usd[1, -1])
    assert table.columns["sale_net_proceeds_usd"][-1] == pytest.approx(vectorized.sale_net_proceeds_usd[1, -1])


def test_columnar_table_from_rows_preserves_columns_and_rejects_ragged_rows() -> None:
    table = columnar_table_from_rows(
        [{"year": 0, "label": "Purchase", "buy_path_usd": 0.0}, {"year": 1, "label": "Year 1", "buy_path_usd": 12.5}]
    )

    assert table.row_count == 2
    assert table.columns == {"year": [0, 1], "label": ["Purchase", "Year 1"], "buy_path_usd": [0.0, 12.5]}
    with pytest.raises(ValueError, match="row 1 keys"):
        columnar_table_from_rows([{"year": 0, "label": "Purchase"}, {"year": 1}])


def test_checking_floor_policy_sells_sp500_when_cash_drops_below_floor() -> None:
    cash_flow = np.array([[0, -7_000, -7_000, 1_000], [0, -3_000, -3_000, -3_000]], dtype="float64")
    portfolio = np.ones_like(cash_flow)
    result = apply_checking_floor_policy(
        net_cash_flow_usd=cash_flow,
        portfolio_multipliers=portfolio,
        initial_checking_usd=12_000,
        initial_brokerage_usd=50_000,
        policy=CheckingFloorPolicy(floor_usd=10_000, sale_amount_usd=20_000),
    )

    np.testing.assert_allclose(result.sp500_sales_usd[0], [0, 20_000, 0, 0])
    np.testing.assert_allclose(result.sp500_sales_usd[1], [0, 20_000, 0, 0])
    assert result.checking_balance_usd.min() >= 9_000
    assert result.brokerage_value_usd[0, -1] == 30_000


if __name__ == "__main__":
    pytest_bazel.main()
