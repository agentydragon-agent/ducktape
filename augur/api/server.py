"""API-only Augur HTTP server entry point."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from augur.api.backend import Backend, BackendRuntimeConfig
from augur.api.config import Config, load_augur_config, resolve_augur_config_path
from augur.api.http_app import create_augur_backend_app
from augur.model.exogenous import ExogenousPathModel
from augur.model.exogenous_provider_config import realize_exogenous_model


@dataclass(frozen=True)
class ApiServerConfig:
    augur_config: Config
    exogenous_model: ExogenousPathModel


def _current_private_equity_price_usd(augur_config: Config) -> float:
    # Every provider must publish the current per-unit private-equity price so the
    # simulator can resolve units-only PrivateEquityPosition entries.
    holdings = augur_config.snapshot.concentrated_holdings
    if len(holdings) != 1:
        raise ValueError(f"expected exactly one concentrated holding for the provider; got {len(holdings)}")
    return float(holdings[0].fmv_usd_per_unit)


def _make_exogenous_model(augur_config: Config, *, current_private_equity_price_usd: float) -> ExogenousPathModel:
    return realize_exogenous_model(
        augur_config.exogenous_provider, current_private_equity_price_usd=current_private_equity_price_usd
    )


def create_app(config: ApiServerConfig) -> FastAPI:
    backend = Backend(
        augur_config=config.augur_config, runtime_config=BackendRuntimeConfig(exogenous_model=config.exogenous_model)
    )
    return create_augur_backend_app(
        title="Augur scenario API",
        bootstrap=backend.bootstrap_payload,
        product_projection_run=backend.run_product_projection,
        scenario_set_run=backend.run_scenario_set,
    )


def create_app_from_augur_config(augur_config: Config) -> FastAPI:
    current_private_equity_price_usd = _current_private_equity_price_usd(augur_config)
    exogenous_model = _make_exogenous_model(
        augur_config, current_private_equity_price_usd=current_private_equity_price_usd
    )
    server_config = ApiServerConfig(augur_config=augur_config, exogenous_model=exogenous_model)
    return create_app(server_config)


def _add_server_args(parser: argparse.ArgumentParser, *, api_only_help: str) -> None:
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--api-only", action="store_true", help=api_only_help)


def build_server_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the Augur backend API.")
    _add_server_args(parser, api_only_help="Accepted for deployment wrappers; this target is already API-only.")
    return parser


def build_configured_server_arg_parser(
    *,
    description: str = "Serve the Augur backend API.",
    api_only_help: str = "Accepted for deployment wrappers; this target is already API-only.",
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--config", help="Path to Config YAML. Defaults to $AUGUR_CONFIG_PATH or /etc/augur/config.yaml."
    )
    _add_server_args(parser, api_only_help=api_only_help)
    return parser


def _run_server_with_args(*, augur_config: Config, args: argparse.Namespace) -> int:
    app = create_app_from_augur_config(augur_config)
    return run_app(app=app, augur_config=augur_config, host=args.host, port=args.port)


def run_app(*, app: FastAPI, augur_config: Config, host: str, port: int) -> int:
    print(f"serving Augur API on http://{host}:{port}")
    print(f"exogenous provider: {augur_config.exogenous_provider.type}")
    uvicorn.run(app, host=host, port=port)
    return 0


def run_server(*, augur_config: Config, argv: list[str] | None = None) -> int:
    return _run_server_with_args(augur_config=augur_config, args=build_server_arg_parser().parse_args(argv))


def run_configured_server(*, argv: list[str] | None = None) -> int:
    args = build_configured_server_arg_parser().parse_args(argv)
    config_path = Path(args.config).resolve() if args.config else resolve_augur_config_path()
    return _run_server_with_args(augur_config=load_augur_config(config_path), args=args)


def main(argv: list[str] | None = None) -> int:
    return run_configured_server(argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
