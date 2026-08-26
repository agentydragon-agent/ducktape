"""Generate the deterministic shared Rust/JAX benchmark fixture.

The file is generated outside timed regions. Values are streamed so the
100,000-rollout fixture does not require a second multi-million-element Python
list in memory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, TextIO


def _scenario(horizon_months: int) -> dict[str, Any]:
    first_sale = horizon_months // 3
    second_sale = 2 * horizon_months // 3
    return {
        "horizon_months": horizon_months,
        "accounts": [
            {"account": {"agent_id": "payroll", "account_id": "checking"}, "opening_balance": 0},
            {"account": {"agent_id": "alice", "account_id": "checking"}, "opening_balance": 1_000_000},
            {"account": {"agent_id": "vendor", "account_id": "checking"}, "opening_balance": 0},
        ],
        "scheduled_transfers": [],
        "recurring_transfers": [
            {
                "start_month": 0,
                "end_month": horizon_months - 1,
                "cause_id": "paycheck",
                "from": {"agent_id": "payroll", "account_id": "checking"},
                "to": {"agent_id": "alice", "account_id": "checking"},
                "amount": 800_000,
            }
        ],
        "obligations": [],
        "recurring_obligations": [
            {
                "start_month": 0,
                "end_month": horizon_months - 1,
                "obligation_id": "living-cost",
                "obligation_type": "cash_spend",
                "from": {"agent_id": "alice", "account_id": "checking"},
                "to": {"agent_id": "vendor", "account_id": "checking"},
                "amount_due": 300_000,
            }
        ],
        "initial_lots": [
            {
                "lot_id": "vti-old",
                "agent_id": "alice",
                "account_id": "brokerage",
                "asset_id": "vti",
                "purchase_month": -24,
                "quantity_scale": 1_000_000,
                "units": 2_000_000,
                "basis": 20_000,
            },
            {
                "lot_id": "vti-new",
                "agent_id": "alice",
                "account_id": "brokerage",
                "asset_id": "vti",
                "purchase_month": -12,
                "quantity_scale": 1_000_000,
                "units": 2_000_000,
                "basis": 24_000,
            },
        ],
        "scheduled_sales": [
            {
                "month": first_sale,
                "cause_id": "sell-vti-1",
                "agent_id": "alice",
                "account_id": "brokerage",
                "asset_id": "vti",
                "units": 1_000_000,
                "proceeds_account_id": "checking",
            },
            {
                "month": second_sale,
                "cause_id": "sell-vti-2",
                "agent_id": "alice",
                "account_id": "brokerage",
                "asset_id": "vti",
                "units": 1_000_000,
                "proceeds_account_id": "checking",
            },
        ],
    }


def _write_repeated_integer(file: TextIO, value: int, count: int) -> None:
    encoded = str(value)
    for index in range(count):
        if index:
            file.write(",")
        file.write(encoded)


def write_fixture(path: Path, *, rollout_count: int, horizon_months: int) -> None:
    if rollout_count <= 0:
        raise ValueError("rollout_count must be positive")
    if horizon_months < 3:
        raise ValueError("horizon_months must be at least 3")
    header = {
        "schema_version": 5,
        "currency_code": "USD",
        "currency_quantum": "0.01",
        "rollout_count": rollout_count,
        "scenario": _scenario(horizon_months),
    }
    with path.open("w") as file:
        file.write(json.dumps(header, separators=(",", ":"))[:-1])
        file.write(',"series":[{"series_id":"security:vti","snapshots":')
        file.write(str(horizon_months + 1))
        file.write(',"values":[')
        _write_repeated_integer(file, 15_000, rollout_count * (horizon_months + 1))
        file.write("]}]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rollouts", type=int, default=100_000)
    parser.add_argument("--horizon-months", type=int, default=60)
    args = parser.parse_args()
    write_fixture(args.output, rollout_count=args.rollouts, horizon_months=args.horizon_months)


if __name__ == "__main__":
    main()
