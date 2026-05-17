"""Generic augur HTTP server entry point.

Reads `AugurConfig` from `--config` or `$AUGUR_CONFIG_PATH` (the latter via
`resolve_augur_config_path`'s fallback chain). Frontend bundle is opt-in:
set `$AUGUR_BUNDLE_INDEX_RUNFILE` to a runfiles-relative path to `index.html`
to serve the bundle from the same process. Otherwise the server starts in
api-only mode and expects a separate static-serving sidecar (production
deployments) or relies on `--dist-dir` at the CLI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from augur.api.config import load_augur_config, resolve_augur_config_path
from augur.api.http_server import ApiOnly, BundleSource, StaticBundle, run_server
from util.bazel.runfiles import get_required_path

_AUGUR_BUNDLE_INDEX_RUNFILE_ENV_VAR = "AUGUR_BUNDLE_INDEX_RUNFILE"


def _split_config_arg(argv: list[str] | None) -> tuple[Path, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--config", help="Path to AugurConfig YAML. Defaults to $AUGUR_CONFIG_PATH or /etc/augur/config.yaml."
    )
    args, remaining = parser.parse_known_args(argv)
    return (Path(args.config).resolve() if args.config else resolve_augur_config_path()), remaining


def _bundle(argv: list[str] | None) -> BundleSource:
    if "--api-only" in (sys.argv[1:] if argv is None else argv):
        return ApiOnly()
    bundle_index_runfile = os.environ.get(_AUGUR_BUNDLE_INDEX_RUNFILE_ENV_VAR)
    if bundle_index_runfile is None:
        # No env var: leave bundle resolution to run_server's CLI handling
        # (--dist-dir overrides; otherwise the parser errors out helpfully).
        return ApiOnly()
    return StaticBundle(dist_dir=get_required_path(bundle_index_runfile).parent)


def main(argv: list[str] | None = None) -> int:
    config_path, remaining = _split_config_arg(argv)
    return run_server(augur_config=load_augur_config(config_path), bundle=_bundle(argv), argv=remaining)


if __name__ == "__main__":
    raise SystemExit(main())
