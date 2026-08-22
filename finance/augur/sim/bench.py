"""Bench script for the representative dense simulator scenario."""

from __future__ import annotations

import argparse
import time

from finance.augur.sim.bench_scenario import build_bench_scenario
from finance.augur.sim.simulate import simulate


def main() -> None:
    parser = argparse.ArgumentParser(description="Augur sim bench")
    parser.add_argument("--rollouts", type=int, default=1000)
    parser.add_argument("--horizon-months", type=int, default=60)
    args = parser.parse_args()

    scenario = build_bench_scenario(horizon_months=args.horizon_months)

    t0 = time.perf_counter()
    result = simulate(scenario, rollout_count=args.rollouts, locations={})
    elapsed = time.perf_counter() - t0

    print(f"rollouts: {args.rollouts}")
    print(f"horizon_months: {args.horizon_months}")
    print(f"wall_clock_sec: {elapsed:.3f}")
    print(f"cash_state_elements: {result.output.state.cash.size}")
    print(f"lot_state_elements: {result.output.state.lots.size}")
    print(f"transfers: {result.events_log.transfers.height}")
    print(f"lot_dispositions: {result.events_log.lot_dispositions.height}")
    print(f"tax_accruals: {result.events_log.tax_accruals.height}")
    print(f"rollout_failures: {result.events_log.rollout_failures.height}")


if __name__ == "__main__":
    main()
