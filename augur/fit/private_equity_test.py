from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import pytest_bazel

from augur.fit.private_equity import (
    PrivateEquityTrainingConfig,
    fit_private_equity_model,
    load_price_observations_jsonl,
    train_from_config,
)
from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.series import private_equity_sale_event_id, private_equity_series_id
from augur.model.trained_private_equity import TrainedPrivateEquityModel, TrainedPrivateEquityModelArtifact


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _rows() -> list[dict[str, object]]:
    return [
        {
            "type": "price_observation",
            "issuer_id": "openai",
            "observed_at": "2023-11-15",
            "kind": "tender_price",
            "price_usd_per_share": 150.0,
            "uncertainty_log_sigma": 0.08,
            "source_id": "test",
            "notes": "synthetic tender",
        },
        {
            "type": "price_observation",
            "issuer_id": "openai",
            "observed_at": "2024-11-15",
            "kind": "tender_price",
            "price_usd_per_share": 210.0,
            "uncertainty_log_sigma": 0.08,
            "source_id": "test",
            "notes": "synthetic tender",
        },
        {
            "type": "price_observation",
            "issuer_id": "openai",
            "observed_at": "2026-05-27",
            "kind": "ppu_mark",
            "price_usd_per_share": 687.69,
            "uncertainty_log_sigma": 0.10,
            "source_id": "shareworks",
            "notes": "synthetic current mark",
        },
    ]


def test_load_jsonl_rejects_non_price_observations(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "observations.jsonl",
        [
            {
                "type": "valuation_observation",
                "issuer_id": "openai",
                "observed_at": "2025-10-28",
                "valuation_usd": 500_000_000_000,
            }
        ],
    )

    with pytest.raises(ValueError, match="unsupported observation type"):
        load_price_observations_jsonl(path)


def test_fit_requires_current_ppu_mark(tmp_path: Path) -> None:
    observations = load_price_observations_jsonl(_write_jsonl(tmp_path / "observations.jsonl", _rows()[:2]))
    config = PrivateEquityTrainingConfig(
        issuer_id="openai", observations_path="observations.jsonl", out_model_path="model.json"
    )

    with pytest.raises(ValueError, match="ppu_mark"):
        fit_private_equity_model(observations, config)


def test_train_round_trips_compact_model_and_runtime_samples(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "observations.jsonl", _rows())
    config_path = tmp_path / "train.yaml"
    config_path.write_text(
        """
issuer_id: openai
observations_path: observations.jsonl
out_model_path: trained_model.json
priors:
  tender_interval_months_median_prior: 3.0
  tender_interval_log_sigma: 0.05
  tender_price_log_discount_sigma: 0.0
""".strip()
        + "\n",
        encoding="utf-8",
    )

    artifact = train_from_config(config_path)
    assert artifact.issuer_id == "openai"
    assert artifact.current_mark_usd == 687.69
    assert artifact.evidence_digest.startswith("sha256:")
    assert (tmp_path / "trained_model.json").exists()

    model = TrainedPrivateEquityModel.from_path(tmp_path / "trained_model.json")
    request = ExogenousSamplingRequest(
        horizon_months=8,
        rollout_seeds=(1, 2, 3),
        required_level_series=frozenset({private_equity_series_id("openai")}),
        required_event_series=frozenset({private_equity_sale_event_id("openai")}),
    )
    bundle = model.sample(request)

    levels = bundle.level_matrix(private_equity_series_id("openai"), rollout_count=3, horizon_months=8)
    assert levels.shape == (3, 9)
    np.testing.assert_allclose(levels[:, 0], np.array([687.69, 687.69, 687.69]))
    assert (levels > 0).all()
    events = bundle.event_matrix(private_equity_sale_event_id("openai"), rollout_count=3, horizon_months=8)
    assert events.dtype.kind == "b"
    assert events.shape == (3, 9)


def test_runtime_sampling_fails_on_nonfinite_private_equity_prices() -> None:
    model = TrainedPrivateEquityModel(
        artifact=TrainedPrivateEquityModelArtifact(
            issuer_id="openai",
            as_of_date="2026-05-27",
            current_mark_usd=687.69,
            monthly_log_return_mu=1000.0,
            monthly_log_return_sigma=0.01,
            tender_interval_months_median=12.0,
            tender_interval_log_sigma=0.1,
            evidence_digest="sha256:test",
        )
    )

    with pytest.raises(ValueError, match="non-finite prices"):
        model.sample(
            ExogenousSamplingRequest(
                horizon_months=1,
                rollout_seeds=(1,),
                required_level_series=frozenset({private_equity_series_id("openai")}),
            )
        )


if __name__ == "__main__":
    pytest_bazel.main()
