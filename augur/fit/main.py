"""Offline exogenous-model training entry point.

Reads an `EvidenceConfig` + source CSVs, fits a chosen `Fittable` model, and
writes two files: a `ExogenousProviderConfig` YAML (the discriminated
deployment config that the augur server reads at startup as part of
`Config.exogenous_provider`) and a per-model trained-state blob (e.g. an
`.npz` archive). The manifest YAML's `trained_blob` is an absolute path so
the deployment authoring it knows exactly where the blob will live at
runtime.

Usage:

    bb run //augur/fit:train -- \\
        --evidence-config augur/fit/config/exogenous_evidence.example.json \\
        --model vecm \\
        --out-provider-config /path/to/exogenous_provider.yaml \\
        --out-blob /path/to/trained_vecm.npz
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from augur.fit.data import DEFAULT_CONFIG_PATH, load_evidence
from augur.fit.evidence_config import load_evidence_config
from augur.model.exogenous_provider_config import VecmExogenousProviderConfig
from augur.model.vecm import VecmConfig, VecmModel

_SUPPORTED_MODEL_LABELS = ("vecm",)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train an Augur exogenous model offline.")
    parser.add_argument(
        "--model", required=True, choices=_SUPPORTED_MODEL_LABELS, help="Which exogenous model to train."
    )
    parser.add_argument(
        "--evidence-config",
        default=DEFAULT_CONFIG_PATH,
        type=Path,
        help="Path to the exogenous evidence config used for training.",
    )
    parser.add_argument(
        "--out-provider-config",
        required=True,
        type=Path,
        help="Absolute path the ExogenousProviderConfig YAML will be written to.",
    )
    parser.add_argument(
        "--out-blob",
        required=True,
        type=Path,
        help="Absolute path the per-model trained state blob will be written to. Echoed into the config verbatim.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    evidence_config_path = args.evidence_config.resolve()
    out_provider_config = args.out_provider_config.resolve()
    out_blob = args.out_blob.resolve()

    config = load_evidence_config(evidence_config_path)
    historical, evidence = load_evidence(config, evidence_config_path.parent)

    model = VecmModel(config=VecmConfig())
    model.fit(historical)
    model.save(out_blob)

    provider_config = VecmExogenousProviderConfig(
        trained_blob=out_blob,
        latest_observations=dict(evidence.latest_observations),
        current_mortgage30_rate_pct=float(evidence.current_mortgage30_rate_pct),
        location_series_sources=config.location_series_sources,
    )

    out_provider_config.write_text(
        yaml.safe_dump(provider_config.model_dump(mode="json"), sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"wrote provider config: {out_provider_config}")
    print(f"wrote trained blob:    {out_blob}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
