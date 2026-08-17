from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest_bazel

from finance.augur.sim.compiler.plan import compile_simulation, lot_order_for_pool
from finance.augur.sim.external_series import ExternalSeriesContext
from finance.augur.sim.scenario import Agent, Currency, InitialAccountBalance, Scenario


def test_compiler_uses_the_scenario_currency_quantum_for_static_money() -> None:
    scenario = Scenario(
        currency=Currency(code="CHF", quantum=Decimal("0.05")),
        agents=[Agent(agent_id="alice")],
        initial_cash=[InitialAccountBalance(agent_id="alice", account_id="checking", balance_usd=1.25)],
        tax_profiles=[],
        horizon_months=1,
    )

    plan = compile_simulation(
        scenario, rollout_count=1, external_series=ExternalSeriesContext(), jurisdictions={}, locations={}
    )

    assert plan.currency_code == "CHF"
    assert plan.currency_quantum == Decimal("0.05")
    assert plan.cash_initial_balance.tolist() == [25, 0]


def test_lot_order_for_pool_is_account_scoped_fifo() -> None:
    order = lot_order_for_pool(
        lot_agent_codes=np.array([1, 1, 1, 1], dtype=np.int64),
        lot_account_codes=np.array([10, 10, 11, 10], dtype=np.int64),
        lot_asset_codes=np.array([20, 20, 20, 21], dtype=np.int64),
        lot_fifo_rank=np.array([5, 2, 1, 0], dtype=np.int64),
        lot_id_codes=np.array([101, 100, 99, 98], dtype=np.int64),
        agent_code=1,
        account_code=10,
        asset_code=20,
    )

    np.testing.assert_array_equal(order, np.array([1, 0], dtype=np.int64))


def test_lot_order_for_pool_breaks_rank_ties_by_lot_id() -> None:
    order = lot_order_for_pool(
        lot_agent_codes=np.array([1, 1, 1], dtype=np.int64),
        lot_account_codes=np.array([10, 10, 10], dtype=np.int64),
        lot_asset_codes=np.array([20, 20, 20], dtype=np.int64),
        lot_fifo_rank=np.array([3, 3, 3], dtype=np.int64),
        lot_id_codes=np.array([102, 100, 101], dtype=np.int64),
        agent_code=1,
        account_code=10,
        asset_code=20,
    )

    np.testing.assert_array_equal(order, np.array([1, 2, 0], dtype=np.int64))


def test_lot_order_for_pool_with_no_eligible_lots_is_empty() -> None:
    order = lot_order_for_pool(
        lot_agent_codes=np.array([1, 1], dtype=np.int64),
        lot_account_codes=np.array([10, 11], dtype=np.int64),
        lot_asset_codes=np.array([20, 20], dtype=np.int64),
        lot_fifo_rank=np.array([0, 1], dtype=np.int64),
        lot_id_codes=np.array([100, 101], dtype=np.int64),
        agent_code=1,
        account_code=12,
        asset_code=20,
    )

    assert order.size == 0


if __name__ == "__main__":
    pytest_bazel.main()
