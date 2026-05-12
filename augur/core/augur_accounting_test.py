from __future__ import annotations

import pytest
import pytest_bazel

from augur.core.augur_accounting import amortization_schedule, monthly_mortgage_payment, resolve_financing
from augur.core.schemas import KnobsConfig


def base_knobs(**overrides: object) -> KnobsConfig:
    values = {
        "down_payment_pct": 25,
        "credit_score": 776,
        "custom_mortgage_rate": 6.5,
        "custom_mortgage_term_years": 20,
        "starting_portfolio_usd": 0,
        "custom_counterfactual_rent_monthly_usd": 0,
        "counterfactual_rent_growth": 3,
        "hold_years": 5,
        "appreciation_rate": 2,
        "sp500_rate": 7,
        "maintenance_pct": 1,
        "owner_occupancy_years": 0,
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
        "insurance_annual_usd": 1800,
        "closing_cost_buy_pct": 2.5,
        "closing_cost_sell_pct": 6.5,
        "cap_gains_exclusion_usd": 250_000,
        "depreciable_basis_pct": 80,
        "financing_mode": "fixed_30",
        "occupancy_type": "investment",
        "rent_counterfactual_mode": "custom",
    }
    values.update(overrides)
    return KnobsConfig.model_validate(values)


def test_monthly_mortgage_payment_matches_textbook_value() -> None:
    payment = monthly_mortgage_payment(200_000, 0.06, 30)
    assert payment == pytest.approx(1199.1, abs=0.5)


def test_monthly_mortgage_payment_zero_rate_is_flat_amortization() -> None:
    assert monthly_mortgage_payment(120_000, 0, 10) == 1000


def test_amortization_schedule_pays_off_full_term() -> None:
    schedule = amortization_schedule(300_000, 0.05, 30, 30)

    assert len(schedule.yearly) == 30
    assert schedule.yearly[-1].balance_usd < 1


def test_amortization_schedule_partial_hold_leaves_residual_balance() -> None:
    schedule = amortization_schedule(300_000, 0.05, 30, 5)

    assert len(schedule.yearly) == 5
    assert schedule.yearly[-1].balance_usd > 250_000
    assert schedule.yearly[-1].balance_usd < 300_000


def test_fixed_15_primary_residence_uses_pmms_baseline_for_excellent_credit() -> None:
    financing = resolve_financing(
        base_knobs(financing_mode="fixed_15", occupancy_type="primary_residence", down_payment_pct=20, credit_score=776)
    )

    assert financing.term_years == 15
    assert financing.rate_pct == pytest.approx(5.58)


def test_cash_mode_zeroes_loan_even_with_lower_down_payment_value() -> None:
    financing = resolve_financing(base_knobs(financing_mode="cash", down_payment_pct=25))

    assert financing.is_cash
    assert financing.down_payment_pct == 100
    assert financing.loan_to_value_pct == 0
    assert financing.rate_pct == 0


if __name__ == "__main__":
    pytest_bazel.main()
