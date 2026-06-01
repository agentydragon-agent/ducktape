"""Run calibration against live Manifold for a deployment config + report the result.

Usage:

    bb run //augur/calibration:calibration_report -- \\
        /path/to/augur/config.yaml \\
        [--preset bayesian_mint_streams] [--rollouts 5000] [--horizon 120]

Loads the catalog and presets from the deployment config, samples the chosen preset model,
runs `run_calibration` against live Manifold prices, and prints scored markets sorted by
KL divergence (loudest disagreement first). Reads no auth — Manifold's market endpoint is
public.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from augur.api.config import load_augur_config
from augur.calibration.calibration import mark_fan, run_calibration
from augur.calibration.catalog import MarketCatalog
from augur.calibration.manifold import ManifoldClient
from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.private_equity_bundle import PrivateEquityFloatChannel
from augur.model.series import IssuerId


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run calibration against live Manifold for a config.")
    parser.add_argument("config", type=Path, help="Path to augur config.yaml")
    parser.add_argument("--preset", default=None, help="Preset id (default = config default)")
    parser.add_argument("--rollouts", type=int, default=5000)
    parser.add_argument("--horizon", type=int, default=120)
    args = parser.parse_args(argv)

    augur_config = load_augur_config(args.config)
    preset_id = args.preset or augur_config.default_exogenous_preset_id
    print(
        f"loaded config: presets={list(augur_config.exogenous_presets)}, default={augur_config.default_exogenous_preset_id}"
    )
    print(f"running preset: {preset_id}")

    catalog_config = augur_config.calibration_catalog
    if catalog_config is None:
        print("error: no calibration_catalog configured", file=sys.stderr)
        return 2
    catalog = MarketCatalog.from_yaml(catalog_config.catalog_path)
    issuer = catalog_config.issuer
    print(f"catalog: issuer={issuer}, n_markets={len(catalog.markets)}")

    provider = augur_config.exogenous_presets[preset_id]
    model = provider.realize_model()
    sampling = ExogenousSamplingRequest(
        horizon_months=args.horizon,
        rollout_seeds=tuple(range(1, args.rollouts + 1)),
        required_private_equity_issuers=frozenset({IssuerId(issuer)}),
    )
    sampled = model.sample(sampling)
    bundle = sampled.private_equity

    price_client = ManifoldClient()
    try:
        result = run_calibration(
            model,
            catalog,
            issuer=issuer,
            horizon_months=args.horizon,
            rollout_seeds=sampling.rollout_seeds,
            price_client=price_client,
            bundle=bundle,
        )
    finally:
        price_client.close()

    mark_pct = mark_fan(
        bundle, issuer=issuer, rollout_count=args.rollouts, horizon_months=args.horizon, percentiles=(5.0, 50.0, 95.0)
    )
    val_pct = mark_fan(
        bundle,
        issuer=issuer,
        rollout_count=args.rollouts,
        horizon_months=args.horizon,
        percentiles=(5.0, 50.0, 95.0),
        channel=PrivateEquityFloatChannel.COMPANY_VALUATION_USD,
    )

    print(f"\n{'=' * 90}")
    print("SCORED MARKETS — sorted by |KL| (loudest disagreement first)")
    print(f"{'=' * 90}")
    print(f"{'p_model':>8s} {'p_market':>9s} {'KL_bits':>9s}  {'slug':32s} question")
    print("-" * 110)
    clean_rows = sorted(result.clean, key=lambda r: -abs(r.kl_bits) if r.kl_bits is not None else 0)
    for clean_row in clean_rows:
        pm = f"{clean_row.p_model:.3f}" if clean_row.p_model is not None else "  n/a"
        kl = f"{clean_row.kl_bits:+.3f}" if clean_row.kl_bits is not None else "  n/a"
        print(f"{pm:>8s} {clean_row.p_market:>9.3f} {kl:>9s}  {clean_row.slug[:32]:32s} {clean_row.question[:60]}")

    print(f"\n{'=' * 90}")
    print("SURFACED MARKETS (not scored, context only)")
    print(f"{'=' * 90}")
    print(f"{'p_market':>9s}  {'slug':32s} question")
    for surfaced_row in result.surfaced:
        print(f"{surfaced_row.p_market:>9.3f}  {surfaced_row.slug[:32]:32s} {surfaced_row.question[:60]}")

    def _band(fan, m: int) -> str:
        month = next((b for b in fan.months if b.month_index == m), None)
        if month is None:
            return "n/a"
        return (
            f"{month.values.get('5.0', 0):.0f} / {month.values.get('50.0', 0):.0f} / {month.values.get('95.0', 0):.0f}"
        )

    print(f"\n{'=' * 90}")
    print("PER-UNIT MARK FAN (p5/p50/p95)")
    print(f"{'=' * 90}")
    for m in (0, 6, 12, 24, 60, 120):
        print(f"  month {m:>3d}:  ${_band(mark_pct, m)}")
    print("\nCOMPANY VALUATION FAN (p5/p50/p95) [$B]")
    for m in (0, 6, 12, 24, 60, 120):
        month = next((b for b in val_pct.months if b.month_index == m), None)
        if month is None:
            continue
        p5 = month.values.get("5.0", 0) / 1e9
        p50 = month.values.get("50.0", 0) / 1e9
        p95 = month.values.get("95.0", 0) / 1e9
        print(f"  month {m:>3d}:  ${p5:.0f}B / ${p50:.0f}B / ${p95:.0f}B")

    return 0


if __name__ == "__main__":
    sys.exit(main())
