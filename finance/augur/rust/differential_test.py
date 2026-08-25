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
from finance.augur.sim.test_state_helpers import (
    asset_lots,
    cash_balances,
    liabilities,
    property_stakes,
    property_state,
    rollout_status,
    tax_liabilities,
)


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


def _tax_payment_fixture(*, funded: bool = True) -> dict[str, Any]:
    fixture = _tax_fixture()
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 13
    scenario["tax_profiles"][0]["prior_year_tax"] = 400_000
    if not funded:
        scenario["tax_profiles"][0]["prior_year_tax"] = 0
        scenario["recurring_transfers"].append(
            {
                "start_month": 0,
                "end_month": 11,
                "cause_id": "alice-spends-paycheck",
                "from": {"agent_id": "alice", "account_id": "checking"},
                "to": {"agent_id": "payroll", "account_id": "checking"},
                "amount": 1_666_667,
            }
        )
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


def _distribution_fixture() -> dict[str, Any]:
    fixture = _fixture()
    scenario = fixture["scenario"]
    scenario["accounts"] = [{"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 0}]
    scenario["scheduled_transfers"] = []
    scenario["recurring_transfers"] = []
    scenario["obligations"] = []
    scenario["recurring_obligations"] = []
    scenario["initial_lots"] = [
        {
            "lot_id": "alice-vti",
            "agent_id": "alice",
            "account_id": "brokerage",
            "asset_id": "vti",
            "purchase_month": -12,
            "quantity_scale": 1_000_000,
            "units": 2_000_000,
            "basis": 20_000,
        }
    ]
    scenario["scheduled_sales"] = []
    scenario["distributions"] = [
        {"agent_id": "alice", "holding_account_id": "brokerage", "asset_id": "vti", "to_account_id": "checking"}
    ]
    fixture["series"] = [
        {"series_id": "security:vti", "snapshots": 4, "values": [10_000] * 8},
        {"series_id": "security_distribution:vti", "snapshots": 4, "values": [100, 100, 100, 100, 200, 300, 400, 500]},
    ]
    return fixture


def _financed_property_fixture() -> dict[str, Any]:
    fixture = _failure_fixture()
    fixture["rollout_count"] = 1
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 2
    scenario["accounts"] = [
        {"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 12_000_000},
        {"account": {"agent_id": "seller", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "bank", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "county", "account_id": "checking"}, "opening_balance": 0},
    ]
    scenario["scheduled_transfers"] = []
    scenario["recurring_transfers"] = []
    scenario["obligations"] = []
    scenario["recurring_obligations"] = []
    scenario["initial_lots"] = []
    scenario["scheduled_sales"] = []
    scenario["locations"] = [
        {
            "location_id": "sf",
            "display_name": "San Francisco",
            "jurisdiction_ids": [],
            "annual_property_tax_rate_ppb": 11_800_000,
            "annual_special_assessment": 0,
        }
    ]
    scenario["scheduled_property_purchases"] = [
        {
            "month": 0,
            "cause_id": "alice-buys-home",
            "property_id": "home",
            "location_id": "sf",
            "buyer_agent_id": "alice",
            "buyer_account_id": "checking",
            "seller_agent_id": "seller",
            "seller_account_id": "checking",
            "purchase_price": 50_000_000,
            "down_payment": 10_000_000,
            "buyer_closing_cost": 1_000_000,
            "mortgage": {
                "liability_id": "home-mortgage",
                "lender_agent_id": "bank",
                "lender_account_id": "checking",
                "principal": 40_000_000,
                "annual_interest_rate_ppb": 60_000_000,
                "term_months": 360,
            },
        }
    ]
    scenario["property_tax_policies"] = [
        {
            "property_id": "home",
            "owner_agent_id": "alice",
            "from_account_id": "checking",
            "tax_authority_agent_id": "county",
            "tax_authority_account_id": "checking",
            "annual_tax_rate_ppb": 12_000_000,
            "start_month": 0,
            "end_month": None,
        }
    ]
    fixture["series"] = []
    return fixture


def _property_cashflow_fixture() -> dict[str, Any]:
    fixture = _financed_property_fixture()
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 12
    scenario["accounts"] = [
        {"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 30_000_000},
        {"account": {"agent_id": "seller", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "bank", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "county", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "tenant", "account_id": "checking"}, "opening_balance": 6_000_000},
        {"account": {"agent_id": "manager", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "irs", "account_id": "checking"}, "opening_balance": 0},
    ]
    scenario["scheduled_property_cashflows"] = [
        {
            "month": 0,
            "property_id": "home",
            "cause_id": "leasing-fee",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "manager", "account_id": "checking"},
            "amount": 100_000,
            "deduction_category": "ordinary",
        }
    ]
    scenario["recurring_property_cashflows"] = [
        {
            "start_month": 0,
            "end_month": 11,
            "property_id": "home",
            "cause_id": "rent",
            "from": {"agent_id": "tenant", "account_id": "checking"},
            "to": {"agent_id": "alice", "account_id": "checking"},
            "amount": 500_000,
            "income_category": "ordinary",
        },
        {
            "start_month": 0,
            "end_month": 11,
            "property_id": "home",
            "cause_id": "management-fee",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "manager", "account_id": "checking"},
            "amount": 50_000,
            "deduction_category": "ordinary",
        },
    ]
    federal_profile = _tax_fixture()["scenario"]["tax_profiles"][0]
    federal_profile["jurisdictions"] = federal_profile["jurisdictions"][:1]
    scenario["tax_profiles"] = [federal_profile]
    return fixture


def _property_cashflow_gating_fixture() -> dict[str, Any]:
    fixture = _failure_fixture()
    fixture["rollout_count"] = 1
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 4
    scenario["accounts"] = [
        {"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 1_000},
        {"account": {"agent_id": "seller", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "vendor", "account_id": "checking"}, "opening_balance": 0},
        {"account": {"agent_id": "creditor", "account_id": "checking"}, "opening_balance": 0},
    ]
    scenario["scheduled_transfers"] = []
    scenario["recurring_transfers"] = []
    scenario["obligations"] = [
        {
            "month": 2,
            "obligation_id": "unaffordable",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "creditor", "account_id": "checking"},
            "amount_due": 876,
        }
    ]
    scenario["recurring_obligations"] = []
    scenario["locations"] = [
        {
            "location_id": "test",
            "display_name": "Test",
            "jurisdiction_ids": [],
            "annual_property_tax_rate_ppb": 0,
            "annual_special_assessment": 0,
        }
    ]
    scenario["scheduled_property_purchases"] = [
        {
            "month": 1,
            "cause_id": "buy-home",
            "property_id": "home",
            "location_id": "test",
            "buyer_agent_id": "alice",
            "buyer_account_id": "checking",
            "seller_agent_id": "seller",
            "seller_account_id": "checking",
            "purchase_price": 100,
            "down_payment": 100,
            "buyer_closing_cost": 0,
            "mortgage": None,
        }
    ]
    scenario["property_tax_policies"] = []
    scenario["scheduled_property_cashflows"] = [
        {
            "month": 0,
            "property_id": "home",
            "cause_id": "before-purchase",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "vendor", "account_id": "checking"},
            "amount": 3,
        },
        {
            "month": 1,
            "property_id": "home",
            "cause_id": "purchase-month",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "vendor", "account_id": "checking"},
            "amount": 5,
        },
    ]
    scenario["recurring_property_cashflows"] = [
        {
            "start_month": 0,
            "end_month": 3,
            "property_id": "home",
            "cause_id": "property-carry",
            "from": {"agent_id": "alice", "account_id": "checking"},
            "to": {"agent_id": "vendor", "account_id": "checking"},
            "amount": 10,
        }
    ]
    scenario["initial_lots"] = []
    scenario["scheduled_sales"] = []
    scenario["tax_profiles"] = []
    scenario["distributions"] = []
    fixture["series"] = []
    return fixture


def _property_sale_fixture() -> dict[str, Any]:
    fixture = _financed_property_fixture()
    fixture["rollout_count"] = 2
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 4
    scenario["accounts"].extend(
        [
            {"account": {"agent_id": "tenant", "account_id": "checking"}, "opening_balance": 10_000},
            {"account": {"agent_id": "gift", "account_id": "checking"}, "opening_balance": 1_000},
        ]
    )
    scenario["scheduled_transfers"] = [
        {
            "month": 2,
            "cause_id": "sale-month-generic-transfer",
            "from": {"agent_id": "gift", "account_id": "checking"},
            "to": {"agent_id": "alice", "account_id": "checking"},
            "amount": 7,
        }
    ]
    scenario["recurring_property_cashflows"] = [
        {
            "start_month": 0,
            "end_month": 3,
            "property_id": "home",
            "cause_id": "rent",
            "from": {"agent_id": "tenant", "account_id": "checking"},
            "to": {"agent_id": "alice", "account_id": "checking"},
            "amount": 1_000,
        }
    ]
    scenario["property_sales"] = [{"month": 2, "property_id": "home", "closing_cost_bps": 600}]
    fixture["series"] = [
        {
            "series_id": "home_value:sf",
            "snapshots": 5,
            "values": [
                50_000_000,
                50_000_000,
                60_000_000,
                60_000_000,
                60_000_000,
                50_000_000,
                50_000_000,
                55_000_000,
                55_000_000,
                55_000_000,
            ],
        }
    ]
    return fixture


def _property_depreciation_fixture(*, sale: bool) -> dict[str, Any]:
    fixture = _property_cashflow_fixture()
    scenario = fixture["scenario"]
    scenario["horizon_months"] = 24 if sale else 12
    purchase = scenario["scheduled_property_purchases"][0]
    purchase["rented_fraction_ppb"] = 0
    purchase["land_value_fraction_ppb"] = 200_000_000
    purchase["mortgage"]["annual_interest_rate_ppb"] = 120_000_000
    scenario["property_tax_policies"] = []
    scenario["property_rented_fraction_events"] = [
        {"month": 6, "property_id": "home", "rented_fraction_ppb": 500_000_000}
    ]
    scenario["capital_improvement_events"] = [
        {"month": 6, "property_id": "home", "amount": 1_000_000, "description": "new roof"}
    ]
    scenario["mortgage_interest_deduction_policies"] = [{"liability_id": "home-mortgage", "owner_agent_id": "alice"}]
    if sale:
        scenario["recurring_property_cashflows"][0]["end_month"] = 23
        scenario["recurring_property_cashflows"][1]["end_month"] = 23
        scenario["property_sales"] = [{"month": 12, "property_id": "home", "closing_cost_bps": 600}]
        tax_profile = _tax_fixture()["scenario"]["tax_profiles"][0]
        tax_profile["jurisdictions"][0]["section_1250_rate_ppb"] = 250_000_000
        tax_profile["jurisdictions"][1]["section_1250_rate_ppb"] = 0
        scenario["tax_profiles"] = [tax_profile]
        fixture["series"] = [
            {"series_id": "home_value:sf", "snapshots": 25, "values": [50_000_000] * 12 + [75_000_000] * 13}
        ]
    return fixture


def _uncapped_mortgage_interest_fixture() -> dict[str, Any]:
    fixture = _property_cashflow_fixture()
    scenario = fixture["scenario"]
    purchase = scenario["scheduled_property_purchases"][0]
    purchase["purchase_price"] = 100_000_000
    purchase["down_payment"] = 20_000_000
    purchase["buyer_closing_cost"] = 1_000_000
    purchase["mortgage"]["principal"] = 80_000_000
    purchase["rented_fraction_ppb"] = 0
    scenario["property_tax_policies"] = []
    scenario["mortgage_interest_deduction_policies"] = [{"liability_id": "home-mortgage", "owner_agent_id": "alice"}]
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


def _rust_tax_liabilities(rust: dict[str, Any]) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for rollout in rust["rollouts"]:
        for snapshot in rollout["months"]:
            rows.extend(
                {
                    "rollout_index": rollout["rollout_id"],
                    "month_index": snapshot["month"],
                    "agent_id": liability["agent_id"],
                    "jurisdiction_id": liability["jurisdiction_id"],
                    "tax_year_end_month": liability["tax_year_end_month"],
                    "amount_owed_quanta": liability["amount_owed"],
                }
                for liability in snapshot["tax_liabilities"]
            )
    return pl.DataFrame(rows).sort("rollout_index", "month_index", "agent_id", "jurisdiction_id", "tax_year_end_month")


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


def test_rust_and_jax_match_estimated_tax_true_up_and_liability_settlement(tmp_path: Path) -> None:
    fixture = _tax_payment_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()

    tax_types = ["estimated_tax", "tax_true_up"]
    legacy_payments = (
        legacy.events_log.obligation_settlements.filter(pl.col("obligation_type").is_in(tax_types))
        .select(
            "month_index",
            pl.col("obligation_id").alias("cause_id"),
            "obligation_type",
            "amount_due_quanta",
            "amount_paid_quanta",
            "shortfall_quanta",
        )
        .sort("month_index", "cause_id")
        .to_dicts()
    )
    rust_payments = sorted(
        [
            {
                "month_index": payment["month"],
                "cause_id": payment["cause_id"],
                "obligation_type": payment["obligation_type"],
                "amount_due_quanta": payment["amount_due"],
                "amount_paid_quanta": payment["amount_paid"],
                "shortfall_quanta": payment["shortfall"],
            }
            for payment in rust["rollouts"][0]["tax_payments"]
        ],
        key=lambda row: (row["month_index"], row["cause_id"]),
    )
    assert rust_payments == legacy_payments

    legacy_liabilities = (
        tax_liabilities(legacy)
        .filter(pl.col("month_index").is_in([12, 13]))
        .sort("rollout_index", "month_index", "agent_id", "jurisdiction_id", "tax_year_end_month")
    )
    rust_liabilities = _rust_tax_liabilities(rust).filter(pl.col("month_index").is_in([12, 13]))
    assert rust_liabilities.to_dicts() == legacy_liabilities.to_dicts()

    legacy_settlements = (
        legacy.events_log.tax_settlements.select(
            "month_index", "cause_id", "agent_id", "tax_year_end_month", "amount_quanta"
        )
        .sort("month_index", "cause_id")
        .to_dicts()
    )
    rust_settlements = sorted(
        [
            {
                "month_index": settlement["month"],
                "cause_id": settlement["cause_id"],
                "agent_id": settlement["agent_id"],
                "tax_year_end_month": settlement["tax_year_end_month"],
                "amount_quanta": settlement["amount"],
            }
            for settlement in rust["rollouts"][0]["tax_settlements"]
        ],
        key=lambda row: (row["month_index"], row["cause_id"]),
    )
    assert rust_settlements == legacy_settlements
    for entry in rust["rollouts"][0]["journal"]:
        assert sum(posting["amount"] for posting in entry["postings"]) == 0


def test_rust_and_jax_match_unfunded_tax_true_up_failure(tmp_path: Path) -> None:
    fixture = _tax_payment_fixture(funded=False)
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    assert rollout_status(legacy).row(0, named=True)["failed_month"] == 12
    assert rust["rollouts"][0]["failed_month"] == 12
    payment = next(
        payment for payment in rust["rollouts"][0]["tax_payments"] if payment["obligation_type"] == "tax_true_up"
    )
    assert payment["cause_id"] == "alice_tax_true_up_y0"
    assert payment["obligation_type"] == "tax_true_up"
    assert payment["amount_paid"] == 0
    assert payment["shortfall"] == payment["amount_due"]
    assert rust["rollouts"][0]["tax_settlements"] == []
    assert _rust_cash(rust).to_dicts() == (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
        .to_dicts()
    )


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


def test_rust_and_jax_match_monthly_security_distributions(tmp_path: Path) -> None:
    fixture = _distribution_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()
    assert [[outcome["amount"] for outcome in rollout["distributions"]] for rollout in rust["rollouts"]] == [
        [200, 200, 200],
        [400, 600, 800],
    ]


def test_rust_and_jax_match_financed_property_purchase_and_first_carry_month(tmp_path: Path) -> None:
    fixture = _financed_property_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()

    legacy_property = property_state(legacy).filter(pl.col("month_index") == 2).row(0, named=True)
    legacy_stake = property_stakes(legacy).filter(pl.col("month_index") == 2).row(0, named=True)
    legacy_mortgage = liabilities(legacy).filter(pl.col("month_index") == 2).row(0, named=True)
    rust_property = rust["rollouts"][0]["months"][2]["properties"][0]
    rust_mortgage = rust["rollouts"][0]["months"][2]["mortgages"][0]
    assert rust_property["property_id"] == legacy_property["property_id"] == "home"
    assert rust_property["location_id"] == legacy_property["location_id"] == "sf"
    assert rust_property["adjusted_basis"] == legacy_property["adjusted_basis_quanta"] == 51_000_000
    assert rust_property["contribution_used"] == legacy_stake["contribution_used_quanta"] == 11_000_000
    assert rust_property["equity_ledger"] == legacy_stake["equity_ledger_quanta"] == 10_000_000
    assert rust_mortgage["liability_id"] == legacy_mortgage["liability_id"] == "home-mortgage"
    assert rust_mortgage["monthly_payment"] == legacy_mortgage["monthly_payment_quanta"] == 239_820
    assert rust_mortgage["principal"] == legacy_mortgage["principal_quanta"] == 39_960_180
    assert rust_mortgage["interest_paid_ytd"] == legacy_mortgage["interest_paid_ytd_quanta"] == 200_000
    assert rust_mortgage["principal_paid_ytd"] == legacy_mortgage["principal_paid_ytd_quanta"] == 39_820

    rust_payment = rust["rollouts"][0]["mortgage_payments"][0]
    legacy_payment = legacy.events_log.mortgage_payments.row(0, named=True)
    assert rust_payment["cause_id"] == legacy_payment["cause_id"] == "home-mortgage_payment_m1"
    assert rust_payment["interest"] == legacy_payment["interest_quanta"] == 200_000
    assert rust_payment["principal"] == legacy_payment["principal_quanta"] == 39_820
    assert rust_payment["total_payment"] == legacy_payment["total_payment_quanta"] == 239_820


def test_rust_and_jax_match_property_cashflows_and_tax_tagging(tmp_path: Path) -> None:
    fixture = _property_cashflow_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()

    legacy_transfers = (
        legacy.events_log.transfers.filter(pl.col("cause_id").is_in(["leasing-fee", "rent", "management-fee"]))
        .group_by("cause_id")
        .agg(pl.len().alias("count"), pl.col("amount_quanta").sum().alias("amount_quanta"))
        .sort("cause_id")
        .to_dicts()
    )
    assert legacy_transfers == [
        {"cause_id": "leasing-fee", "count": 1, "amount_quanta": 100_000},
        {"cause_id": "management-fee", "count": 12, "amount_quanta": 600_000},
        {"cause_id": "rent", "count": 12, "amount_quanta": 6_000_000},
    ]
    rust_causes = [entry["cause_id"] for entry in rust["rollouts"][0]["journal"]]
    assert rust_causes.count("leasing-fee") == 1
    assert rust_causes.count("management-fee") == 12
    assert rust_causes.count("rent") == 12

    legacy_tax = legacy.events_log.tax_breakdowns.row(0, named=True)
    rust_tax = rust["rollouts"][0]["tax_accruals"][0]
    assert rust_tax["ordinary_income"] == legacy_tax["ordinary_income_quanta"] == 5_300_000
    assert rust_tax["total_tax"] == legacy_tax["total_tax_quanta"] == 437_600


def test_rust_and_jax_match_property_cashflow_purchase_and_failure_gates(tmp_path: Path) -> None:
    fixture = _property_cashflow_gating_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()
    assert rollout_status(legacy).to_dicts() == [
        {"rollout_index": 0, "status": "failed_insufficient_cash", "failed_month": 2}
    ]
    assert rust["rollouts"][0]["failed_month"] == 2

    legacy_property_cashflows = (
        legacy.events_log.transfers.filter(
            pl.col("cause_id").is_in(["before-purchase", "purchase-month", "property-carry"])
        )
        .select("month_index", "cause_id")
        .sort("month_index", "cause_id")
        .to_dicts()
    )
    assert legacy_property_cashflows == [
        {"month_index": 1, "cause_id": "property-carry"},
        {"month_index": 1, "cause_id": "purchase-month"},
        {"month_index": 2, "cause_id": "property-carry"},
    ]
    rust_property_cashflows = sorted(
        [
            {"month_index": entry["month"], "cause_id": entry["cause_id"]}
            for entry in rust["rollouts"][0]["journal"]
            if entry["cause_id"] in {"before-purchase", "purchase-month", "property-carry"}
        ],
        key=lambda row: (row["month_index"], row["cause_id"]),
    )
    assert rust_property_cashflows == legacy_property_cashflows


def test_rust_and_jax_match_property_sale_lifecycle_and_rollout_values(tmp_path: Path) -> None:
    fixture = _property_sale_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()

    legacy_sales = (
        legacy.events_log.property_sale_events.select(
            "rollout_index",
            "month_index",
            "property_id",
            "gross_proceeds_quanta",
            "mortgage_payoff_quanta",
            "net_cash_to_owner_quanta",
            "realized_gain_quanta",
            "depreciation_recapture_quanta",
            "section_121_exclusion_quanta",
            "long_term_capital_gain_quanta",
        )
        .sort("rollout_index")
        .to_dicts()
    )
    rust_sales = sorted(
        [
            {
                "rollout_index": rollout["rollout_id"],
                "month_index": sale["month"],
                "property_id": sale["property_id"],
                "gross_proceeds_quanta": sale["gross_proceeds"],
                "mortgage_payoff_quanta": sale["mortgage_payoff"],
                "net_cash_to_owner_quanta": sale["net_cash_to_owner"],
                "realized_gain_quanta": sale["realized_gain"],
                "depreciation_recapture_quanta": sale["depreciation_recapture"],
                "section_121_exclusion_quanta": sale["section_121_exclusion"],
                "long_term_capital_gain_quanta": sale["long_term_capital_gain"],
            }
            for rollout in rust["rollouts"]
            for sale in rollout["property_sales"]
        ],
        key=lambda row: row["rollout_index"],
    )
    assert rust_sales == legacy_sales
    assert [row["gross_proceeds_quanta"] for row in rust_sales] == [56_400_000, 51_700_000]

    assert property_state(legacy).filter(pl.col("month_index") >= 3).is_empty()
    assert liabilities(legacy).filter(pl.col("month_index") >= 3).is_empty()
    for rollout in rust["rollouts"]:
        post_sale = rollout["months"][3]
        assert post_sale["properties"][0]["active"] is False
        assert post_sale["mortgages"][0]["active"] is False
        assert post_sale["mortgages"][0]["principal"] == 0
        sale_month_causes = [entry["cause_id"] for entry in rollout["journal"] if entry["month"] == 2]
        assert "property-sale:home" in sale_month_causes
        assert "sale-month-generic-transfer" in sale_month_causes
        assert "rent" not in sale_month_causes
        assert "home-mortgage_payment_m2" not in sale_month_causes
        assert "home_property_tax_m2" not in sale_month_causes
        for entry in rollout["journal"]:
            assert sum(posting["amount"] for posting in entry["postings"]) == 0


def test_rust_and_jax_match_rental_transition_capex_depreciation_and_interest(tmp_path: Path) -> None:
    fixture = _property_depreciation_fixture(sale=False)
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_cash = (
        cash_balances(legacy)
        .select("rollout_index", "month_index", "agent_id", "account_id", "balance_quanta")
        .sort("rollout_index", "month_index", "agent_id", "account_id")
    )
    assert _rust_cash(rust).to_dicts() == legacy_cash.to_dicts()
    assert legacy.events_log.set_rented_fraction_events.select(
        "month_index", "property_id", "rented_fraction"
    ).to_dicts() == [{"month_index": 6, "property_id": "home", "rented_fraction": 0.5}]
    assert legacy.events_log.capital_improvement_events.select(
        "month_index", "property_id", "amount_quanta", "description"
    ).to_dicts() == [{"month_index": 6, "property_id": "home", "amount_quanta": 1_000_000, "description": ""}]
    rollout = rust["rollouts"][0]
    assert rollout["property_rented_fraction_events"] == [
        {"month": 6, "property_id": "home", "rented_fraction_ppb": 500_000_000}
    ]
    assert rollout["capital_improvements"] == [
        {"month": 6, "property_id": "home", "amount": 1_000_000, "description": ""}
    ]
    # Lifecycle changes apply before this month's depreciation and mortgage split.
    first_depreciation = rollout["months"][7]["properties"][0]["cumulative_depreciation"]
    assert first_depreciation > 0
    assert rollout["months"][6]["properties"][0]["cumulative_depreciation"] == 0

    legacy_tax = legacy.events_log.tax_breakdowns.row(0, named=True)
    rust_tax = rollout["tax_accruals"][0]
    assert rust_tax["ordinary_income"] == legacy_tax["ordinary_income_quanta"]
    assert rust_tax["mortgage_interest_deduction"] == legacy_tax["mortgage_interest_deduction_quanta"]
    assert rust_tax["itemized_deduction"] == legacy_tax["itemized_deduction_quanta"]
    assert rust_tax["ordinary_taxable"] == legacy_tax["ordinary_taxable_quanta"]
    assert rust_tax["total_tax"] == legacy_tax["total_tax_quanta"]
    assert rust_tax["rental_interest_deduction"] > 0
    assert rust_tax["depreciation_deduction"] > 0


def test_rust_and_jax_match_uncapped_acquisition_mortgage_interest(tmp_path: Path) -> None:
    fixture = _uncapped_mortgage_interest_fixture()
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_tax = legacy.events_log.tax_breakdowns.row(0, named=True)
    rollout = rust["rollouts"][0]
    rust_tax = rollout["tax_accruals"][0]
    total_interest = sum(payment["interest"] for payment in rollout["mortgage_payments"])
    assert rust_tax["mortgage_interest_deduction"] == total_interest
    assert rust_tax["mortgage_interest_deduction"] == legacy_tax["mortgage_interest_deduction_quanta"]
    assert rust_tax["itemized_deduction"] == legacy_tax["itemized_deduction_quanta"]
    assert rust_tax["total_tax"] == legacy_tax["total_tax_quanta"]


def test_rust_and_jax_match_depreciation_recapture_and_jurisdiction_tax(tmp_path: Path) -> None:
    fixture = _property_depreciation_fixture(sale=True)
    legacy = run_legacy_fixture(fixture)
    rust = _rust_run(fixture, tmp_path)

    legacy_sales = legacy.events_log.property_sale_events.select(
        "month_index",
        "property_id",
        "gross_proceeds_quanta",
        "mortgage_payoff_quanta",
        "net_cash_to_owner_quanta",
        "realized_gain_quanta",
        "depreciation_recapture_quanta",
        "section_121_exclusion_quanta",
        "long_term_capital_gain_quanta",
    ).to_dicts()
    rust_sale = rust["rollouts"][0]["property_sales"][0]
    assert [
        {
            "month_index": rust_sale["month"],
            "property_id": rust_sale["property_id"],
            "gross_proceeds_quanta": rust_sale["gross_proceeds"],
            "mortgage_payoff_quanta": rust_sale["mortgage_payoff"],
            "net_cash_to_owner_quanta": rust_sale["net_cash_to_owner"],
            "realized_gain_quanta": rust_sale["realized_gain"],
            "depreciation_recapture_quanta": rust_sale["depreciation_recapture"],
            "section_121_exclusion_quanta": rust_sale["section_121_exclusion"],
            "long_term_capital_gain_quanta": rust_sale["long_term_capital_gain"],
        }
    ] == legacy_sales
    assert rust_sale["depreciation_recapture"] > 0

    legacy_tax = legacy.events_log.tax_breakdowns.filter(pl.col("month_index") == 23).sort("jurisdiction_id").to_dicts()
    rust_tax = sorted(
        [row for row in rust["rollouts"][0]["tax_accruals"] if row["month"] == 23],
        key=lambda row: row["jurisdiction_id"],
    )
    assert [row["jurisdiction_id"] for row in rust_tax] == [row["jurisdiction_id"] for row in legacy_tax]
    for rust_row, legacy_row in zip(rust_tax, legacy_tax, strict=True):
        assert rust_row["ordinary_income"] == legacy_row["ordinary_income_quanta"]
        assert rust_row["long_term_gain"] == legacy_row["ltcg_quanta"]
        assert rust_row["ordinary_taxable"] == legacy_row["ordinary_taxable_quanta"]
        assert rust_row["long_term_capital_gain_taxable"] == legacy_row["capital_gain_taxable_quanta"]
        assert rust_row["ordinary_tax"] == legacy_row["ordinary_tax_quanta"]
        assert rust_row["capital_gain_tax"] == legacy_row["capital_gain_tax_quanta"]
        assert rust_row["total_tax"] == legacy_row["total_tax_quanta"]
        assert rust_row["section_1250_recapture"] == rust_sale["depreciation_recapture"]
    rust_tax_by_jurisdiction = {row["jurisdiction_id"]: row for row in rust_tax}
    assert rust_tax_by_jurisdiction["federal_us"]["section_1250_tax"] > 0
    assert rust_tax_by_jurisdiction["california"]["section_1250_tax"] == 0


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
