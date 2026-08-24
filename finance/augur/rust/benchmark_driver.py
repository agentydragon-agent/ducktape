"""Generate a canonical fixture and run the optimized Rust summary benchmark."""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from python.runfiles import runfiles

from finance.augur.rust.benchmark_fixture import write_fixture


def _binary() -> Path:
    resolver = runfiles.Create()
    if resolver is None:
        raise RuntimeError("Bazel runfiles are unavailable")
    path = resolver.Rlocation("_main/finance/augur/rust/simulator_bench")
    if path is None:
        raise RuntimeError("simulator_bench is absent from runfiles")
    return Path(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollouts", type=int, default=100_000)
    parser.add_argument("--horizon-months", type=int, default=60)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "fixture.json"
        write_fixture(fixture, rollout_count=args.rollouts, horizon_months=args.horizon_months)
        completed = subprocess.run([_binary(), fixture, str(args.repeats)], check=True, capture_output=True, text=True)
        report: dict[str, Any] = json.loads(completed.stdout)
        report.update(
            {
                "fixture_bytes": fixture.stat().st_size,
                "logical_cpu_count": os.cpu_count(),
                "rayon_num_threads": os.environ.get("RAYON_NUM_THREADS"),
                "peak_child_rss_kb": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            }
        )
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
