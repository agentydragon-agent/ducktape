"""Generic augur HTTP server. A deployment-side wrapper (e.g. gaffer's
serve.py) provides the `AugurConfig`, bundle source, then calls
`run_server(...)`. The market-bundle provider is selected by the
type-discriminated `AugurConfig.market_provider` config."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from augur.api.backend import AugurBackend, AugurBackendRuntimeConfig
from augur.api.config import AugurConfig
from augur.core.backend import StaticPathResolver, create_augur_backend_app
from augur.core.market_bundle import MarketBundleProvider
from augur.model.market_provider_config import realize_core_market_provider, realize_market_model
from augur.model.sim_market_api import JointMarketModel


@dataclass(frozen=True)
class StaticBundle:
    """Serve the React bundle from `dist_dir` alongside the API."""

    dist_dir: Path


@dataclass(frozen=True)
class ApiOnly:
    """Serve only JSON API routes; static assets are external."""


BundleSource = StaticBundle | ApiOnly


@dataclass(frozen=True)
class AugurServerConfig:
    augur_config: AugurConfig
    market_model: JointMarketModel
    market_bundle_provider: MarketBundleProvider
    default_rollout_samples: int
    max_rollout_samples: int
    bundle: BundleSource


def _current_private_equity_price_usd(augur_config: AugurConfig) -> float:
    # Every provider must publish the current per-unit private-equity price so the
    # simulator can resolve units-only PrivateEquityPosition entries (the browser
    # stores units and lets the simulator own the mark).
    holdings = augur_config.snapshot.concentrated_holdings
    if len(holdings) != 1:
        raise ValueError(f"expected exactly one concentrated holding for the provider; got {len(holdings)}")
    return float(holdings[0].fmv_usd_per_unit)


def _make_market_model(augur_config: AugurConfig, *, current_private_equity_price_usd: float) -> JointMarketModel:
    return realize_market_model(
        augur_config.market_provider, current_private_equity_price_usd=current_private_equity_price_usd
    )


def _make_core_market_provider(
    augur_config: AugurConfig, *, market_model: JointMarketModel, current_private_equity_price_usd: float
) -> MarketBundleProvider:
    return realize_core_market_provider(
        augur_config.market_provider,
        model=market_model,
        current_private_equity_price_usd=current_private_equity_price_usd,
    )


def _static_path_resolver(bundle: BundleSource) -> StaticPathResolver | None:
    if not isinstance(bundle, StaticBundle):
        return None
    dist_dir = bundle.dist_dir

    def resolve(full_path: str) -> Path:
        # Strip absolute/traversal paths to a sentinel that will 404 in
        # FastAPI's FileResponse. Unknown SPA routes fall back to index.html so
        # the React router can take over.
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

    return resolve


def create_app(config: AugurServerConfig):
    backend = AugurBackend(
        augur_config=config.augur_config,
        runtime_config=AugurBackendRuntimeConfig(
            market_bundle_provider=config.market_bundle_provider,
            default_rollout_samples=config.default_rollout_samples,
            max_rollout_samples=config.max_rollout_samples,
        ),
    )
    return create_augur_backend_app(
        title="Augur scenario API",
        static_path=_static_path_resolver(config.bundle),
        bootstrap=backend.bootstrap_payload,
        scenario_set_run=backend.run_scenario_set_for_request_body,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the combined property-first Augur backend API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument(
        "--api-only", action="store_true", help="Serve only JSON API routes; static assets are external."
    )
    parser.add_argument("--dist-dir", help="Override the prebuilt frontend bundle directory.")
    return parser


def _resolve_bundle(
    args: argparse.Namespace, default_bundle: BundleSource, parser: argparse.ArgumentParser
) -> BundleSource:
    if args.api_only:
        return ApiOnly()
    if args.dist_dir:
        return StaticBundle(dist_dir=Path(args.dist_dir).resolve())
    if isinstance(default_bundle, ApiOnly):
        parser.error("--dist-dir is required when the deployment provides no bundle and --api-only is not set")
    return default_bundle


def run_server(*, augur_config: AugurConfig, bundle: BundleSource, argv: list[str] | None = None) -> int:
    """Run the Augur HTTP server with the supplied AugurConfig and bundle source.

    Deployment-side entry points (e.g. gaffer's `serve.py`) pass in a
    `StaticBundle` (default) or `ApiOnly`; this module never references
    `_main/` directly. `--api-only` overrides the supplied bundle;
    `--dist-dir` overrides the default `StaticBundle`. The market model is
    selected by the type-discriminated `AugurConfig.market_provider` object
    loaded by the deployment."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    current_private_equity_price_usd = _current_private_equity_price_usd(augur_config)
    market_model = _make_market_model(augur_config, current_private_equity_price_usd=current_private_equity_price_usd)
    market_bundle_provider = _make_core_market_provider(
        augur_config, market_model=market_model, current_private_equity_price_usd=current_private_equity_price_usd
    )
    server_config = AugurServerConfig(
        augur_config=augur_config,
        market_model=market_model,
        market_bundle_provider=market_bundle_provider,
        default_rollout_samples=augur_config.default_rollout_samples,
        max_rollout_samples=augur_config.max_rollout_samples,
        bundle=_resolve_bundle(args, bundle, parser),
    )
    app = create_app(server_config)
    print(f"serving Augur on http://{args.host}:{args.port}")
    print(f"market provider: {augur_config.market_provider.type}")
    match server_config.bundle:
        case StaticBundle(dist_dir=dist_dir):
            print(f"static bundle: {dist_dir}")
        case ApiOnly():
            print("static bundle: disabled")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0
