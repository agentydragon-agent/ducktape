from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import pytest_bazel

from augur.model.conditioning import ExogenousConditioningContext, ExogenousObservedPoint, ObservationTreatment
from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.location_series_sources import LocationSeriesSourcesConfig
from augur.model.series import (
    INFLATION_SERIES_ID,
    SP500_SERIES_ID,
    crypto_series_id,
    home_value_series_id,
    private_equity_series_id,
    rent_series_id,
)
from augur.model.state_space import (
    StateSpaceExogenousProviderConfig,
    StateSpaceModelArtifact,
    StateSpacePrivateEquityEventPrior,
    write_state_space_artifact,
)
from augur.model.trained_private_equity import TrainedPrivateEquityScalePrior


def test_state_space_samples_all_available_series_and_hard_anchors(tmp_path: Path) -> None:
    provider = _provider(tmp_path, sp500_anchor=123.0)
    sampled = provider.realize_model().sample(
        ExogenousSamplingRequest(
            rollout_seeds=(7, 8), horizon_months=3, required_level_series=frozenset({INFLATION_SERIES_ID})
        )
    )

    series_ids = set(sampled.levels.get_column("series_id").unique().to_list())
    assert series_ids >= {
        SP500_SERIES_ID,
        INFLATION_SERIES_ID,
        crypto_series_id("btc"),
        home_value_series_id("san_francisco_ca"),
        home_value_series_id("mare_island_vallejo_ca"),
        rent_series_id("san_francisco_ca"),
    }
    assert sampled.private_equity.issuer_ids() >= frozenset({"private_company_a"})
    np.testing.assert_allclose(
        sampled.level_matrix(SP500_SERIES_ID, rollout_count=2, horizon_months=3)[:, 0], np.array([123.0, 123.0])
    )
    assert sampled.private_equity.issuer_bool_matrix(
        "private_company_a", "sale_opportunity_active", rollout_count=2, horizon_months=3
    ).shape == (2, 4)
    source_manifest = cast(dict[str, Any], sampled.metadata["source_manifest"])
    prior_manifest = cast(dict[str, Any], sampled.metadata["prior_manifest"])
    assert source_manifest["source_ids"] == ["fixture:public"]
    assert prior_manifest["kind"] == "fixture"


def test_state_space_conditioning_changes_sampled_paths(tmp_path: Path) -> None:
    low = (
        _provider(tmp_path / "low", sp500_anchor=100.0)
        .realize_model()
        .sample(ExogenousSamplingRequest(rollout_seeds=(11,), horizon_months=3))
    )
    high = (
        _provider(tmp_path / "high", sp500_anchor=200.0)
        .realize_model()
        .sample(ExogenousSamplingRequest(rollout_seeds=(11,), horizon_months=3))
    )

    low_sp500 = low.level_matrix(SP500_SERIES_ID, rollout_count=1, horizon_months=3)
    high_sp500 = high.level_matrix(SP500_SERIES_ID, rollout_count=1, horizon_months=3)
    np.testing.assert_allclose(high_sp500, low_sp500 * 2.0)


def test_state_space_private_equity_marks_forward_fill_between_tenders(tmp_path: Path) -> None:
    sampled = (
        _provider(
            tmp_path, sp500_anchor=100.0, pe_tender_interval_months_median=120.0, pe_tender_interval_log_sigma=1e-12
        )
        .realize_model()
        .sample(
            ExogenousSamplingRequest(
                rollout_seeds=(11,), horizon_months=4, required_private_equity_issuers=frozenset({"private_company_a"})
            )
        )
    )

    levels = sampled.private_equity.issuer_float_matrix(
        "private_company_a", "mark_usd_per_unit", rollout_count=1, horizon_months=4
    )
    np.testing.assert_allclose(levels, np.full((1, 5), 687.69))


def test_state_space_hard_fails_missing_required_series(tmp_path: Path) -> None:
    model = _provider(tmp_path, sp500_anchor=123.0).realize_model()

    with pytest.raises(ValueError, match="missing required level series"):
        model.sample(
            ExogenousSamplingRequest(
                rollout_seeds=(1,), horizon_months=1, required_level_series=frozenset({"prices_of_tea_in_china"})
            )
        )


def _provider(
    path: Path,
    *,
    sp500_anchor: float,
    pe_tender_interval_months_median: float = 2.0,
    pe_tender_interval_log_sigma: float = 0.1,
) -> StateSpaceExogenousProviderConfig:
    path.mkdir(parents=True, exist_ok=True)
    artifact_path = path / "state_space.json"
    write_state_space_artifact(
        artifact_path,
        _artifact(
            pe_tender_interval_months_median=pe_tender_interval_months_median,
            pe_tender_interval_log_sigma=pe_tender_interval_log_sigma,
        ),
    )
    conditioning = ExogenousConditioningContext(
        start_at=date(2026, 5, 1),
        observations={
            SP500_SERIES_ID: (
                ExogenousObservedPoint(
                    value=sp500_anchor,
                    observed_at=date(2026, 5, 1),
                    source_id="fixture:sp500",
                    treatment=ObservationTreatment.HARD_START,
                ),
            )
        },
    )
    return StateSpaceExogenousProviderConfig(
        trained_artifact_path=artifact_path,
        conditioning=conditioning,
        current_mortgage30_rate_pct=6.25,
        location_series_sources=LocationSeriesSourcesConfig(
            home_value={
                "san_francisco_ca": "home_value:san_francisco_ca",
                "mare_island_vallejo_ca": "home_value:san_francisco_ca",
            },
            rent={"san_francisco_ca": "rent:san_francisco_ca"},
        ),
    )


def _artifact(
    *, pe_tender_interval_months_median: float = 2.0, pe_tender_interval_log_sigma: float = 0.1
) -> StateSpaceModelArtifact:
    factors = (
        SP500_SERIES_ID,
        INFLATION_SERIES_ID,
        crypto_series_id("btc"),
        home_value_series_id("san_francisco_ca"),
        rent_series_id("san_francisco_ca"),
        private_equity_series_id("private_company_a"),
    )
    latest = {
        SP500_SERIES_ID: 100.0,
        INFLATION_SERIES_ID: 320.0,
        crypto_series_id("btc"): 80_000.0,
        home_value_series_id("san_francisco_ca"): 1_400_000.0,
        rent_series_id("san_francisco_ca"): 530.0,
        private_equity_series_id("private_company_a"): 687.69,
    }
    mu = {
        SP500_SERIES_ID: 0.005,
        INFLATION_SERIES_ID: 0.002,
        crypto_series_id("btc"): 0.01,
        home_value_series_id("san_francisco_ca"): 0.003,
        rent_series_id("san_francisco_ca"): 0.0025,
        private_equity_series_id("private_company_a"): 0.01,
    }
    cov = np.diag([0.04**2, 0.003**2, 0.2**2, 0.01**2, 0.006**2, 0.08**2])
    return StateSpaceModelArtifact(
        factor_names=factors,
        trained_through_month="2026-04",
        latest_level_by_factor=latest,
        monthly_log_return_mu=mu,
        monthly_log_return_cov=tuple(tuple(float(value) for value in row) for row in cov),
        filtered_log_state_mean={factor: float(np.log(latest[factor])) for factor in factors},
        filtered_log_state_cov=tuple(tuple(float(value) for value in row) for row in cov),
        private_equity_event_priors={
            "private_company_a": StateSpacePrivateEquityEventPrior(
                tender_interval_months_median=pe_tender_interval_months_median,
                tender_interval_log_sigma=pe_tender_interval_log_sigma,
                last_tender_observed_at=date(2026, 1, 1),
            )
        },
        private_equity_scale_priors={
            "private_company_a": TrainedPrivateEquityScalePrior(
                current_market_cap_usd=7_000_000_000.0,
                soft_cap_market_cap_usd=5_000_000_000_000.0,
                monthly_log_drift_penalty=0.08,
            )
        },
        source_manifest={"source_ids": ("fixture:public",)},
        prior_manifest={"kind": "fixture"},
    )


if __name__ == "__main__":
    pytest_bazel.main()
