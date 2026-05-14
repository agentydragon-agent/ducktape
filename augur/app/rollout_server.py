"""Generic augur HTTP server. A deployment-side wrapper (e.g. gaffer's
serve.py) provides the `AugurConfig`, frontend bundle dir, and rollout
config path, then calls `run_server(...)`."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from augur.app.augur_backend import AugurBackend
from augur.app.config import AugurConfig
from augur.core.backend import create_augur_backend_app
from augur.core.market_bundle import FlatMarketBundleProvider, MarketBundleProvider, SimpleMarketBundleProvider
from augur.core.rollout_provider import RolloutProvider
from augur.core.static import static_path_for_dist
from augur.model.macro_rollout_provider import MacroRolloutProvider
from augur.model.markets.registry import LABELS

_BUILT_IN_PROVIDER_LABELS = ("noop", "simple")


def _make_provider(
    args: argparse.Namespace, augur_config: AugurConfig, default_rollout_config_path: Path
) -> tuple[RolloutProvider | None, MarketBundleProvider | None]:
    if args.provider == "noop":
        return None, FlatMarketBundleProvider()
    if args.provider == "simple":
        return None, SimpleMarketBundleProvider()
    # MacroRolloutProvider currently supports a single private-equity holding.
    holdings = augur_config.snapshot.concentrated_holdings
    if len(holdings) != 1:
        raise ValueError(f"expected exactly one concentrated holding for the macro provider; got {len(holdings)}")
    rollout_config_path = Path(args.rollout_config).resolve() if args.rollout_config else default_rollout_config_path
    return (
        MacroRolloutProvider.for_label(
            args.provider,
            config_path=rollout_config_path,
            current_private_equity_price_usd=holdings[0].fmv_usd_per_unit,
        ),
        None,
    )


def create_app(
    *,
    augur_config: AugurConfig,
    rollout_provider: RolloutProvider | None,
    market_bundle_provider: MarketBundleProvider | None = None,
    default_rollout_samples: int,
    max_rollout_samples: int,
    dist_dir: Path,
):
    augur_backend = AugurBackend(
        augur_config=augur_config,
        rollout_provider=rollout_provider,
        market_bundle_provider=market_bundle_provider,
        default_rollout_samples=default_rollout_samples,
        max_rollout_samples=max_rollout_samples,
    )
    return create_augur_backend_app(
        title="Augur rollout API",
        static_path=lambda full_path: static_path_for_dist(dist_dir, full_path),
        bootstrap=augur_backend.bootstrap_payload,
        scenario_set_run=augur_backend.run_scenario_set_for_request_body,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the combined property-first Augur backend API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--rollout-config", help="Path to the joint rollout config JSON.")
    parser.add_argument(
        "--provider",
        choices=(*_BUILT_IN_PROVIDER_LABELS, *LABELS),
        default="vecm",
        help="Market provider: built-in noop/simple or a macro rollout provider from augur.model.markets.registry.",
    )
    parser.add_argument("--dist-dir", help="Override the prebuilt frontend bundle directory.")
    parser.add_argument("--rollout-samples", type=int, default=None)
    parser.add_argument("--max-rollout-samples", type=int, default=2048)
    return parser


def run_server(
    *, augur_config: AugurConfig, dist_dir: Path, default_rollout_config_path: Path, argv: list[str] | None = None
) -> int:
    """Run the Augur HTTP server with the supplied AugurConfig and bundle dir.

    Deployment-side entry points (e.g. gaffer's `serve.py`) resolve their
    runfile paths and pass them in; this module is module-agnostic and never
    references `_main/` directly. CLI args drive transport and rollout-provider
    choice; AugurConfig drives everything user-specific."""
    args = _build_arg_parser().parse_args(argv)
    rollout_provider, market_bundle_provider = _make_provider(args, augur_config, default_rollout_config_path)
    if args.dist_dir:
        dist_dir = Path(args.dist_dir).resolve()
    print(f"serving Augur on http://{args.host}:{args.port}")
    print(f"rollout provider: {rollout_provider.label if rollout_provider is not None else args.provider}")
    print(f"static bundle: {dist_dir}")
    uvicorn.run(
        create_app(
            augur_config=augur_config,
            rollout_provider=rollout_provider,
            market_bundle_provider=market_bundle_provider,
            default_rollout_samples=args.rollout_samples or augur_config.default_rollout_samples,
            max_rollout_samples=args.max_rollout_samples,
            dist_dir=dist_dir,
        ),
        host=args.host,
        port=args.port,
    )
    return 0
