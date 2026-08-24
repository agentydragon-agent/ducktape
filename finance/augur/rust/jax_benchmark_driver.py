"""Run the existing JAX simulator on the canonical Rust benchmark fixture."""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import tempfile
import time
from pathlib import Path
from typing import Any

import jax
import numpy as np

from finance.augur.rust.benchmark_fixture import write_fixture
from finance.augur.rust.fixture_adapter import build_legacy_fixture
from finance.augur.sim.simulate import simulate_with_external_series


def _checksum(arrays: list[np.ndarray[Any, Any]]) -> int:
    value = 0xCBF29CE484222325
    for array in arrays:
        for byte in np.ascontiguousarray(array).view(np.uint8).flat:
            value ^= int(byte)
            value = (value * 0x00000100000001B3) & ((1 << 64) - 1)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollouts", type=int, default=100_000)
    parser.add_argument("--horizon-months", type=int, default=60)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="rollouts retained in one dense JAX output; defaults to all rollouts",
    )
    args = parser.parse_args()
    if args.repeats <= 0:
        parser.error("--repeats must be positive")
    batch_size = args.batch_size or args.rollouts
    if batch_size <= 0 or args.rollouts % batch_size:
        parser.error("--batch-size must be positive and divide --rollouts exactly")
    batch_count = args.rollouts // batch_size

    with tempfile.TemporaryDirectory() as directory:
        fixture_path = Path(directory) / "fixture.json"
        write_fixture(fixture_path, rollout_count=batch_size, horizon_months=args.horizon_months)
        with fixture_path.open() as file:
            fixture: dict[str, Any] = json.load(file)
        scenario, external = build_legacy_fixture(fixture)
        del fixture
        gc.collect()

        def run():
            result = simulate_with_external_series(
                scenario, rollout_count=batch_size, external_series=external, locations={}
            )
            jax.block_until_ready(result.output.state.cash)
            return result

        cold_started = time.perf_counter()
        run()
        cold_seconds = time.perf_counter() - cold_started

        durations = []
        result = None
        for _ in range(args.repeats):
            started = time.perf_counter()
            for _ in range(batch_count):
                result = run()
            durations.append(time.perf_counter() - started)
        assert result is not None
        sorted_durations = sorted(durations)
        median = sorted_durations[len(sorted_durations) // 2]
        output = result.output
        final_failed = np.asarray(output.state.failed[-1], dtype=np.bool_)
        report = {
            "rollout_count": args.rollouts,
            "batch_size": batch_size,
            "batch_count": batch_count,
            "horizon_months": args.horizon_months,
            "repeats": args.repeats,
            "cold_wall_seconds": cold_seconds,
            "wall_seconds": durations,
            "median_wall_seconds": median,
            "rollouts_per_second": args.rollouts / median,
            "rollout_months_per_second": args.rollouts * args.horizon_months / median,
            "fixture_bytes_per_batch": fixture_path.stat().st_size,
            "logical_fixture_bytes": fixture_path.stat().st_size * batch_count,
            "logical_cpu_count": os.cpu_count(),
            "peak_self_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "jax_backend": jax.default_backend(),
            "jax_devices": [str(device) for device in jax.devices()],
            "cash_state_elements_per_batch": int(output.state.cash.size),
            "lot_state_elements_per_batch": int(output.state.lots.size),
            "obligation_elements_per_batch": int(output.obligations.due.size),
            "failure_count": int(final_failed.sum()) * batch_count,
            "batch_checksum": _checksum(
                [
                    np.asarray(output.state.cash[-1]),
                    np.asarray(output.state.lots[-1]),
                    final_failed,
                    np.asarray(output.state.failed_month[-1]),
                ]
            ),
        }
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
