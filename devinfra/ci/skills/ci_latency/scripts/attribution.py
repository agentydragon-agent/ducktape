#!/usr/bin/env python3
"""Attribute measured additive compute time to triggers with exact OR-game Shapley values.

Input is a reviewed JSON object with runs: [{id, source_commit, units: [{name,
seconds, triggers: [..], kind}]}]. A unit is incurred iff any of its triggers
is present; Shapley of that OR game assigns seconds / number of triggers to each.
Only independent, non-overlapping units of the SAME resource can be added.
"""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def calculate(data):
    totals = defaultdict(float)
    by_kind = defaultdict(lambda: defaultdict(float))
    coverage = defaultdict(float)
    runs = data["runs"]
    if not runs:
        raise ValueError("no runs")
    resource = data["resource"]
    if not isinstance(resource, str) or not resource.strip():
        raise ValueError("resource must identify a single additive cost unit")
    for run in runs:
        if not run.get("id") or not run.get("source_commit"):
            raise ValueError("run needs id and source_commit")
        for unit in run["units"]:
            cost = unit["seconds"]
            triggers = unit["triggers"]
            kind = unit["kind"]
            if not isinstance(cost, (int, float)) or isinstance(cost, bool) or not math.isfinite(cost) or cost < 0:
                raise ValueError("unit seconds must be finite and nonnegative")
            if not isinstance(triggers, list) or not triggers or any(not isinstance(t, str) or not t for t in triggers):
                raise ValueError("unit needs nonempty trigger names")
            if len(set(triggers)) != len(triggers) or not isinstance(kind, str) or not kind:
                raise ValueError("duplicate trigger or missing kind")
            coverage[kind] += cost
            for trigger in triggers:
                totals[trigger] += cost / len(triggers)
                by_kind[trigger][kind] += cost / len(triggers)
    result = {"resource": resource, "run_count": len(runs), "measured_seconds": sum(coverage.values()),
              "measured_by_kind_seconds": dict(sorted(coverage.items())),
              "attribution": [{"trigger": k, "seconds": v, "by_kind_seconds": dict(sorted(by_kind[k].items()))}
                              for k, v in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))]}
    if not math.isclose(sum(totals.values()), result["measured_seconds"], rel_tol=1e-12, abs_tol=1e-7):
        raise ValueError("attribution does not reconcile")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(calculate(json.loads(args.input.read_text())), indent=2) + "\n")


if __name__ == "__main__":
    main()
