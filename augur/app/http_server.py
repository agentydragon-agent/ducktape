"""Generic augur HTTP server. A deployment-side wrapper (e.g. gaffer's
serve.py) provides the `AugurConfig`, frontend bundle dir, and market
config path, then calls `run_server(...)`."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from augur.app.augur_backend import AugurBackend, AugurBackendRuntimeConfig
from augur.app.config import AugurConfig
from augur.core.backend import create_augur_backend_app
from augur.core.market_bundle import FlatMarketBundleProvider, MarketBundleProvider, SimpleMarketBundleProvider
from augur.model.macro_market_bundle_provider import MacroMarketBundleProvider
from augur.model.markets.registry import LABELS

_BUILT_IN_PROVIDER_LABELS = ("noop", "simple")


@dataclass(frozen=True)
class AugurApiServerConfig:
    augur_config: AugurConfig
    market_bundle_provider: MarketBundleProvider
    default_rollout_samples: int
    max_rollout_samples: int


@dataclass(frozen=True)
class AugurStaticServerConfig:
    api: AugurApiServerConfig
    dist_dir: Path


def _make_provider(
    args: argparse.Namespace, augur_config: AugurConfig, default_market_config_path: Path
) -> MarketBundleProvider:
    if args.provider == "noop":
        return FlatMarketBundleProvider()
    if args.provider == "simple":
        return SimpleMarketBundleProvider()
    # MacroMarketBundleProvider currently uses one concentrated holding's current
    # valuation to populate private-equity source metadata.
    holdings = augur_config.snapshot.concentrated_holdings
    if len(holdings) != 1:
        raise ValueError(f"expected exactly one concentrated holding for the macro provider; got {len(holdings)}")
    market_config_path = Path(args.market_config).resolve() if args.market_config else default_market_config_path
    return MacroMarketBundleProvider.for_label(
        args.provider, config_path=market_config_path, current_private_equity_price_usd=holdings[0].fmv_usd_per_unit
    )


def _static_path_for_dist(dist_dir: Path, full_path: str) -> Path:
    rel = "index.html" if full_path in ("", "/") else full_path.lstrip("/")
    relative = Path(rel)
    if relative.is_absolute() or ".." in relative.parts:
        return dist_dir / "__forbidden__"
    candidate = dist_dir / relative
    if candidate.exists():
        return candidate
    if candidate.suffix:
        return candidate
    return dist_dir / "index.html"


def _create_backend(config: AugurApiServerConfig) -> AugurBackend:
    return AugurBackend(
        augur_config=config.augur_config,
        runtime_config=AugurBackendRuntimeConfig(
            market_bundle_provider=config.market_bundle_provider,
            default_rollout_samples=config.default_rollout_samples,
            max_rollout_samples=config.max_rollout_samples,
        ),
    )


def create_static_app(config: AugurStaticServerConfig):
    augur_backend = _create_backend(config.api)
    return create_augur_backend_app(
        title="Augur scenario API",
        static_path=lambda full_path: _static_path_for_dist(config.dist_dir, full_path),
        bootstrap=augur_backend.bootstrap_payload,
        scenario_set_run=augur_backend.run_scenario_set_for_request_body,
    )


def create_api_app(config: AugurApiServerConfig):
    augur_backend = _create_backend(config)
    return create_augur_backend_app(
        title="Augur scenario API",
        static_path=None,
        bootstrap=augur_backend.bootstrap_payload,
        scenario_set_run=augur_backend.run_scenario_set_for_request_body,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the combined property-first Augur backend API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--market-config", help="Path to the market model config JSON.")
    parser.add_argument(
        "--api-only", action="store_true", help="Serve only JSON API routes; static assets are external."
    )
    parser.add_argument(
        "--provider",
        choices=(*_BUILT_IN_PROVIDER_LABELS, *LABELS),
        default="vecm",
        help="Market provider: built-in noop/simple or a macro model provider from augur.model.markets.registry.",
    )
    parser.add_argument("--dist-dir", help="Override the prebuilt frontend bundle directory.")
    parser.add_argument("--rollout-samples", type=int, default=None)
    parser.add_argument("--max-rollout-samples", type=int, default=2048)
    return parser


def run_server(
    *, augur_config: AugurConfig, dist_dir: Path | None, default_market_config_path: Path, argv: list[str] | None = None
) -> int:
    """Run the Augur HTTP server with the supplied AugurConfig and bundle dir.

    Deployment-side entry points (e.g. gaffer's `serve.py`) resolve their
    runfile paths and pass them in; this module is module-agnostic and never
    references `_main/` directly. CLI args drive transport and market-provider
    choice; AugurConfig drives everything user-specific."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    market_bundle_provider = _make_provider(args, augur_config, default_market_config_path)
    api_config = AugurApiServerConfig(
        augur_config=augur_config,
        market_bundle_provider=market_bundle_provider,
        default_rollout_samples=args.rollout_samples or augur_config.default_rollout_samples,
        max_rollout_samples=args.max_rollout_samples,
    )
    if args.dist_dir:
        dist_dir = Path(args.dist_dir).resolve()
    if args.api_only:
        app = create_api_app(api_config)
    else:
        if dist_dir is None:
            parser.error("--dist-dir or deployment-provided dist_dir is required unless --api-only is set")
        app = create_static_app(AugurStaticServerConfig(api=api_config, dist_dir=dist_dir))
    print(f"serving Augur on http://{args.host}:{args.port}")
    print(f"market provider: {args.provider}")
    print(f"static bundle: {'disabled' if args.api_only else dist_dir}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0
