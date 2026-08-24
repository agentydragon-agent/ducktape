"""Differential harness for the Rust and existing JAX simulators.

The canonical fixture is integer-only. Both engines consume the same scenario
and exogenous bytes; conversion to legacy floats happens only inside the
existing Python/JAX adapter because that engine predates this boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest
import pytest_bazel

from finance.augur.rust.benchmark_fixture import write_fixture
from finance.augur.rust.fixture_adapter import run_legacy_fixture
from finance.augur.sim.test_state_helpers import asset_lots, cash_balances, rollout_status


def _binary() -> Path:
    runfiles = Path(os.environ["TEST_SRCDIR"])
    workspace = os.environ["TEST_WORKSPACE"]
    return runfiles / workspace / "finance/augur/rust/simulator_cli"


def _fixture() -> dict[str, Any]:
    # Prices are cents per whole unit and quantities are millionths of a unit.
    # The two rollouts deliberately use different paths before the scheduled
    # sale, while sharing the sale-month value supported by the legacy fixed
    # sale-price surface.
    return {
        "schema_version": 1,
        "currency_code": "USD",
        "currency_quantum": "0.01",
        "rollout_count": 2,
        "scenario": {
            "horizon_months": 3,
            "accounts": [
                {"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 1_000},
                {"account": {"agent_id": "bob", "account_id": "checking"}, "opening_balance": 2_000},
            ],
            "scheduled_transfers": [
                {
                    "month": 0,
                    "cause_id": "bob_gives_alice_5",
                    "from": {"agent_id": "bob", "account_id": "checking"},
                    "to": {"agent_id": "alice", "account_id": "checking"},
                    "amount": 500,
                }
            ],
            "recurring_transfers": [
                {
                    "start_month": 1,
                    "end_month": 2,
                    "cause_id": "paycheck",
                    "from": {"agent_id": "bob", "account_id": "checking"},
                    "to": {"agent_id": "alice", "account_id": "checking"},
                    "amount": 100,
                }
            ],
            "obligations": [
                {
                    "month": 2,
                    "obligation_id": "required-payment",
                    "from": {"agent_id": "alice", "account_id": "checking"},
                    "to": {"agent_id": "bob", "account_id": "checking"},
                    "amount_due": 50,
                }
            ],
            "initial_lots": [
                {
                    "lot_id": "alice-vti",
                    "agent_id": "alice",
                    "account_id": "checking",
                    "asset_id": "vti",
                    "purchase_month": -12,
                    "quantity_scale": 1_000_000,
                    "units": 2_000_000,
                    "basis": 20_000,
                }
            ],
            "scheduled_sales": [
                {
                    "month": 1,
                    "cause_id": "sell-vti",
                    "agent_id": "alice",
                    "account_id": "checking",
                    "asset_id": "vti",
                    "units": 1_000_000,
                    "proceeds_account_id": "checking",
                }
            ],
        },
        "series": [
            {
                "series_id": "security:vti",
                "snapshots": 4,
                "values": [10_000, 15_000, 15_000, 15_000, 20_000, 15_000, 15_000, 15_000],
            }
        ],
    }


def _failure_fixture() -> dict[str, Any]:
    fixture = _fixture()
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 2
    scenario["accounts"] = [
        {"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 100},
        {"account": {"agent_id": "bob", "account_id": "checking"}, "opening_balance": 0},
    ]
    scenario["scheduled_transfers"] = [
        {
            "month": 1,
            "cause_id": "must-not-run",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "bob", "account_id": "checking"},
            "amount": 1,
        }
    ]
    scenario["recurring_transfers"] = []
    scenario["obligations"] = [
        {
            "month": 0,
            "obligation_id": "too-large",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "bob", "account_id": "checking"},
            "amount_due": 101,
        }
    ]
    scenario["initial_lots"] = []
    scenario["scheduled_sales"] = []
    fixture["series"] = []
    return fixture


def _recurring_obligation_fixture() -> dict[str, Any]:
    fixture = _failure_fixture()
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 3
    scenario["accounts"] = [
        {"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 100_000},
        {"account": {"agent_id": "landlord", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "utility", "account_id": "checking"}, "opening_balance": 0},
    ]
    scenario["scheduled_transfers"] = []
    scenario["obligations"] = []
    scenario["recurring_obligations"] = [
        {
            "start_month": 0,
            "end_month": 2,
            "obligation_id": "rent",
            "obligation_type": "cash_spend",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "landlord", "account_id": "checking"},
            "amount_due": 60_000,
        },
        {
            "start_month": 1,
            "end_month": 2,
            "obligation_id": "utility",
            "obligation_type": "cash_spend",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "utility", "account_id": "checking"},
            "amount_due": 1,
        },
    ]
    return fixture


def _tax_fixture() -> dict[str, Any]:
    fixture = _failure_fixture()
    fixture["rollout_count"] = 1
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 12
    scenario["accounts"] = [
        {"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "payroll", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "irs", "account_id": "checking"}, "opening_balance": 0},
    ]
    scenario["scheduled_transfers"] = []
    scenario["recurring_transfers"] = [
        {
            "start_month": 0,
            "end_month": 11,
            "cause_id": "alice-paycheck",
            "from": {"agent_id": "payroll", "account_id": "checking"},
            "to": {"agent_id": "alice", "account_id": "checking"},
            "amount": 1_666_667,
            "income_category": "ordinary",
        }
    ]
    scenario["obligations"] = []
    scenario["recurring_obligations"] = []
    scenario["tax_profiles"] = [
        {
            "agent_id": "alice",
            "tax_authority_agent_id": "irs",
            "jurisdictions": [
                {
                    "jurisdiction_id": "federal_us",
                    "ordinary_brackets": [
                        {"upper": 1_160_000, "rate_ppb": 100_000_000},
                        {"upper": 4_715_000, "rate_ppb": 120_000_000},
                        {"upper": 10_052_500, "rate_ppb": 220_000_000},
                        {"upper": 19_195_000, "rate_ppb": 240_000_000},
                        {"upper": None, "rate_ppb": 320_000_000},
                    ],
                    "long_term_capital_gain_brackets": [
                        {"upper": 4_702_500, "rate_ppb": 0},
                        {"upper": None, "rate_ppb": 150_000_000},
                    ],
                    "standard_deduction": 1_460_000,
                    "max_capital_loss_ordinary_offset": 300_000,
                },
                {
                    "jurisdiction_id": "california",
                    "ordinary_brackets": [
                        {"upper": 1_041_200, "rate_ppb": 10_000_000},
                        {"upper": 2_468_400, "rate_ppb": 20_000_000},
                        {"upper": 3_895_900, "rate_ppb": 40_000_000},
                        {"upper": 5_408_100, "rate_ppb": 60_000_000},
                        {"upper": 6_835_000, "rate_ppb": 80_000_000},
                        {"upper": None, "rate_ppb": 93_000_000},
                    ],
                    "long_term_capital_gain_brackets": [],
                    "standard_deduction": 536_300,
                    "max_capital_loss_ordinary_offset": 300_000,
                },
            ],
        }
    ]
    return fixture


def _long_term_gain_tax_fixture() -> dict[str, Any]:
    fixture = _tax_fixture()
    scenario = fixture["scenario"]
    scenario["recurring_transfers"][0]["amount"] = 416_667
    scenario["initial_lots"] = [
        {
            "lot_id": "alice-vti",
            "agent_id": "alice",
            "account_id": "brokerage",
            "asset_id": "vti",
            "purchase_month": -24,
            "quantity_scale": 1_000_000,
            "units": 100_000_000,
            "basis": 1_000_000,
        }
    ]
    scenario["scheduled_sales"] = [
        {
            "month": 6,
            "cause_id": "sell-vti",
            "agent_id": "alice",
            "account_id": "brokerage",
            "asset_id": "vti",
            "units": 100_000_000,
            "proceeds_account_id": "checking",
        }
    ]
    scenario["tax_profiles"][0]["jurisdictions"] = scenario["tax_profiles"][0]["jurisdictions"][:1]
    fixture["series"] = [{"series_id": "security:vti", "snapshots": 13, "values": [30_000] * 13}]
    return fixture


def _rust_run(fixture: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    fixture_path = tmp_path / "fixture.json"
    output_path = tmp_path / "rust-output.json"
    fixture_path.write_text(json.dumps(fixture, separators=(",", ":")))
    subprocess.run([_binary(), fixture_path, output_path], check=True)
    return cast(dict[str, Any], json.loads(output_path.read_text()))


def _rust_cash(rust: dict[str, Any]) -> pl.DataFrame:
    rows = []
    for rollout in rust["rollouts"]:
        for snapshot in rollout["months"]:
            for balance in snapshot["balances"]:
                account = balance["account"]
                if account["account_id"] == "checking":
                    rows.append(
                        {
                            "rollout_index": rollout["rollout_id"],
                            "month_index": snapshot["month"],
                            "agent_id": account["agent_id"],
                            "account_id": account["account_id"],
                            "balance_quanta": balance["balance"],
                        }
                    )
    return pl.DataFrame(rows).sort("rollout_index", "month_index", "agent_id", "account_id")


def test_rust_and_jax_match_on_shared_integer_fixture(tmp_path: Path) -> None:
    fixture = _fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()

    legacy_dispositions = (
        legacy.events_log.lot_dispositions.with_columns(
            (pl.col("units_sold") * 1_000_000).round().cast(pl.Int64).alias("units_sold_quanta")
        )
        .select(
            "rollout_index",
            "month_index",
            "lot_id",
            "units_sold_quanta",
            "cost_basis_consumed_quanta",
            "proceeds_quanta",
        )
        .sort("rollout_index", "month_index", "lot_id")
        .to_dicts()
    )
    rust_dispositions = sorted(
        [
            {
                "rollout_index": rollout["rollout_id"],
                "month_index": disposition["month"],
                "lot_id": disposition["lot_id"],
                "units_sold_quanta": disposition["units"],
                "cost_basis_consumed_quanta": disposition["basis"],
                "proceeds_quanta": disposition["proceeds"],
            }
            for rollout in rust["rollouts"]
            for disposition in rollout["dispositions"]
        ],
        key=lambda row: (row["rollout_index"], row["month_index"], row["lot_id"]),
    )
    assert rust_dispositions == legacy_dispositions

    # The existing lot read model must also agree on the post-sale quantity.
    legacy_final_lots = asset_lots(legacy).filter(pl.col("month_index") == 3)
    assert legacy_final_lots.get_column("remaining_quantity_quanta").to_list() == [1_000_000, 1_000_000]

    for rollout in rust["rollouts"]:
        for entry in rollout["journal"]:
            assert sum(posting["amount"] for posting in entry["postings"]) == 0


def test_rust_and_jax_match_failure_freeze_semantics(tmp_path: Path) -> None:
    fixture = _failure_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()

    assert rollout_status(legacy).to_dicts() == [
        {"rollout_index": 0, "status": "failed_insufficient_cash", "failed_month": 0},
        {"rollout_index": 1, "status": "failed_insufficient_cash", "failed_month": 0},
    ]
    assert [rollout["failed_month"] for rollout in rust["rollouts"]] == [0, 0]
    assert all(
        snapshot["failed"] and all(balance["balance"] == 0 for balance in snapshot["balances"])
        for rollout in rust["rollouts"]
        for snapshot in rollout["months"][1:]
    )


def test_rust_and_jax_match_grouped_recurring_obligations(tmp_path: Path) -> None:
    fixture = _recurring_obligation_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()
    assert rollout_status(legacy).to_dicts() == [
        {"rollout_index": 0, "status": "failed_insufficient_cash", "failed_month": 1},
        {"rollout_index": 1, "status": "failed_insufficient_cash", "failed_month": 1},
    ]

    columns = [
        "rollout_index",
        "month_index",
        "obligation_id",
        "obligation_type",
        "agent_id",
        "from_account_id",
        "amount_due_quanta",
        "amount_paid_quanta",
        "shortfall_quanta",
    ]
    legacy_outcomes = legacy.events_log.obligation_settlements.select(columns).sort(columns[:3]).to_dicts()
    rust_outcomes = sorted(
        [
            {
                "rollout_index": rollout["rollout_id"],
                "month_index": outcome["month"],
                "obligation_id": outcome["obligation_id"],
                "obligation_type": outcome["obligation_type"],
                "agent_id": outcome["from"]["agent_id"],
                "from_account_id": outcome["from"]["account_id"],
                "amount_due_quanta": outcome["amount_due"],
                "amount_paid_quanta": outcome["amount_paid"],
                "shortfall_quanta": outcome["shortfall"],
            }
            for rollout in rust["rollouts"]
            for outcome in rollout["obligations"]
        ],
        key=lambda row: (row["rollout_index"], row["month_index"], row["obligation_id"]),
    )
    assert rust_outcomes == legacy_outcomes


def test_generated_benchmark_fixture_matches_at_seventeen_rollouts(tmp_path: Path) -> None:
    fixture_path = tmp_path / "benchmark-fixture.json"
    write_fixture(fixture_path, rollout_count=17, horizon_months=12)
    fixture = cast(dict[str, Any], json.loads(fixture_path.read_text()))
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()

    legacy_dispositions = (
        legacy.events_log.lot_dispositions.with_columns(
            (pl.col("units_sold") * 1_000_000).round().cast(pl.Int64).alias("units_sold_quanta")
        )
        .select(
            "rollout_index",
            "month_index",
            "lot_id",
            "units_sold_quanta",
            "cost_basis_consumed_quanta",
            "proceeds_quanta",
        )
        .sort("rollout_index", "month_index", "lot_id")
        .to_dicts()
    )
    rust_dispositions = sorted(
        [
            {
                "rollout_index": rollout["rollout_id"],
                "month_index": disposition["month"],
                "lot_id": disposition["lot_id"],
                "units_sold_quanta": disposition["units"],
                "cost_basis_consumed_quanta": disposition["basis"],
                "proceeds_quanta": disposition["proceeds"],
            }
            for rollout in rust["rollouts"]
            for disposition in rollout["dispositions"]
        ],
        key=lambda row: (row["rollout_index"], row["month_index"], row["lot_id"]),
    )
    assert rust_dispositions == legacy_dispositions
    assert rollout_status(legacy).get_column("status").unique().to_list() == ["active"]
    assert all(rollout["failed_month"] is None for rollout in rust["rollouts"])


def test_rust_and_jax_match_federal_and_california_tax_accruals(tmp_path: Path) -> None:
    fixture = _tax_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()

    columns = [
        "rollout_index",
        "month_index",
        "agent_id",
        "jurisdiction_id",
        "ordinary_income_quanta",
        "ordinary_taxable_quanta",
        "capital_gain_taxable_quanta",
        "ordinary_tax_quanta",
        "capital_gain_tax_quanta",
        "total_tax_quanta",
    ]
    legacy_accruals = legacy.events_log.tax_breakdowns.select(columns).sort("jurisdiction_id").to_dicts()
    rust_accruals = sorted(
        [
            {
                "rollout_index": rollout["rollout_id"],
                "month_index": accrual["month"],
                "agent_id": accrual["agent_id"],
                "jurisdiction_id": accrual["jurisdiction_id"],
                "ordinary_income_quanta": accrual["ordinary_income"],
                "ordinary_taxable_quanta": accrual["ordinary_taxable"],
                "capital_gain_taxable_quanta": accrual["long_term_capital_gain_taxable"],
                "ordinary_tax_quanta": accrual["ordinary_tax"],
                "capital_gain_tax_quanta": accrual["capital_gain_tax"],
                "total_tax_quanta": accrual["total_tax"],
            }
            for rollout in rust["rollouts"]
            for accrual in rollout["tax_accruals"]
        ],
        key=lambda row: row["jurisdiction_id"],
    )
    assert rust_accruals == legacy_accruals
    assert [row["total_tax_quanta"] for row in rust_accruals] == [1_475_409, 3_753_851]
    for entry in rust["rollouts"][0]["journal"]:
        assert sum(posting["amount"] for posting in entry["postings"]) == 0


def test_rust_and_jax_match_long_term_gain_tax(tmp_path: Path) -> None:
    fixture = _long_term_gain_tax_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_row = legacy.events_log.tax_breakdowns.row(0, named=True)
    rust_row = rust["rollouts"][0]["tax_accruals"][0]
    assert rust_row["ordinary_income"] == legacy_row["ordinary_income_quanta"]
    assert rust_row["long_term_gain"] == legacy_row["ltcg_quanta"] == 2_000_000
    assert rust_row["ordinary_taxable"] == legacy_row["ordinary_taxable_quanta"] == 3_540_004
    assert rust_row["long_term_capital_gain_taxable"] == legacy_row["capital_gain_taxable_quanta"] == 2_000_000
    assert rust_row["ordinary_tax"] == legacy_row["ordinary_tax_quanta"] == 401_600
    assert rust_row["capital_gain_tax"] == legacy_row["capital_gain_tax_quanta"] == 125_626
    assert rust_row["total_tax"] == legacy_row["total_tax_quanta"] == 527_226


@pytest.mark.parametrize("rollout_count", [1, 17])
def test_fixture_contains_no_floating_point_numbers(rollout_count: int) -> None:
    fixture = _fixture()
    fixture["rollout_count"] = rollout_count
    fixture["series"][0]["values"] = fixture["series"][0]["values"][:4] * rollout_count

    def walk(value: Any) -> None:
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(fixture)


if __name__ == "__main__":
    pytest_bazel.main()
