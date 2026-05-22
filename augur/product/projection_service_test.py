from __future__ import annotations

from dataclasses import dataclass, field

import pytest_bazel

from augur.api.config import load_augur_config
from augur.model.exogenous import ExogenousSamplingRequest, SampledExogenousBundle
from augur.model.series import SP500_SERIES_ID
from augur.model.simple_exogenous import SimpleExogenousModel
from augur.product.projection import MetricFanRequest, RolloutRequest, ScenarioKey
from augur.product.projection_service import ProductProjectionCache, ProductProjectionService
from util.bazel.runfiles import get_required_path


@dataclass
class CountingExogenousModel:
    sample_requests: list[ExogenousSamplingRequest] = field(default_factory=list)

    def sample(self, request: ExogenousSamplingRequest) -> SampledExogenousBundle:
        self.sample_requests.append(request)
        return SimpleExogenousModel().sample(request)


def _service(model: CountingExogenousModel) -> ProductProjectionService:
    return ProductProjectionService(
        augur_config=load_augur_config(get_required_path("_main/augur/api/testdata/config.yaml")),
        exogenous_model=model,
        cache=ProductProjectionCache(max_rollouts=10),
    )


def _scenario_key() -> ScenarioKey:
    return ScenarioKey(
        exogenous_model_id="current_exogenous_model", horizon_months=3, monthly_spend_usd=1_000.0, spend_index="none"
    )


def test_metric_fan_and_rollout_detail_share_cached_sim_rollouts() -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = _scenario_key()

    fan = service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="cash_usd", percentiles=(0, 50, 100))
    )

    assert [request.rollout_seeds for request in model.sample_requests] == [(7, 8)]
    assert model.sample_requests[0].required_level_series == frozenset({SP500_SERIES_ID})
    assert fan.exogenous_model_id == "simple_exogenous_model"
    assert fan.metric == "cash_usd"
    assert fan.failed_count == 0
    assert [summary.seed for summary in fan.rollout_summaries] == [7, 8]
    assert [summary.sort_rank for summary in fan.rollout_summaries] == [0, 1]
    assert [summary.rank_percentile for summary in fan.rollout_summaries] == [25.0, 75.0]
    assert [summary.terminal_metrics.cash_usd for summary in fan.rollout_summaries] == [47_000.0, 47_000.0]
    assert fan.monthly_metric_fan.row_count == 12
    assert fan.monthly_metric_fan.columns["month_index"] == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3]
    assert fan.monthly_metric_fan.columns["percentile"] == [0.0, 50.0, 100.0] * 4
    assert fan.monthly_metric_fan.columns["value"] == [
        50_000.0,
        50_000.0,
        50_000.0,
        49_000.0,
        49_000.0,
        49_000.0,
        48_000.0,
        48_000.0,
        48_000.0,
        47_000.0,
        47_000.0,
        47_000.0,
    ]
    assert fan.terminal_metric_percentiles.columns == {"percentile": [0.0, 50.0, 100.0], "value": [47_000.0] * 3}

    detail = service.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert [request.rollout_seeds for request in model.sample_requests] == [(7, 8)]
    assert detail.exogenous_model_id == "simple_exogenous_model"
    assert detail.rollout.seed == 7
    assert detail.rollout.monthly_metrics.columns["cash_usd"] == [50_000.0, 49_000.0, 48_000.0, 47_000.0]
    assert detail.rollout.monthly_metrics.columns["public_security_value_usd"][0] == 150_000.0
    assert detail.rollout.monthly_metrics.columns["liquid_net_worth_usd"][0] == 200_000.0
    assert detail.rollout.monthly_metrics.columns["net_worth_usd"][0] == 200_000.0

    public_security_fan = service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8), metric="public_security_value_usd", percentiles=(50,))
    )

    assert public_security_fan.monthly_metric_fan.columns["value"][0] == 150_000.0

    fan_with_one_new_seed = service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7, 8, 9), metric="cash_usd", percentiles=(50,))
    )

    assert [request.rollout_seeds for request in model.sample_requests] == [(7, 8), (9,)]
    assert fan_with_one_new_seed.monthly_metric_fan.columns["percentile"] == [50.0] * 4


def test_failed_rollout_metrics_freeze_at_zero_after_failure() -> None:
    model = CountingExogenousModel()
    service = _service(model)
    scenario = ScenarioKey(
        exogenous_model_id="current_exogenous_model", horizon_months=3, monthly_spend_usd=100_000.0, spend_index="none"
    )

    fan = service.metric_fan(
        MetricFanRequest(scenario=scenario, rollout_seeds=(7,), metric="net_worth_usd", percentiles=(50,))
    )

    assert fan.failed_count == 1
    assert fan.monthly_metric_fan.columns["month_index"] == [0, 1, 2, 3]
    assert fan.monthly_metric_fan.columns["value"] == [200_000.0, 0.0, 0.0, 0.0]
    [summary] = fan.rollout_summaries
    assert summary.failed is True
    assert summary.terminal_metrics.failed_month_index == 0
    assert summary.terminal_metrics.cash_usd == 0.0
    assert summary.terminal_metrics.public_security_value_usd == 0.0
    assert summary.terminal_metrics.net_worth_usd == 0.0
    assert summary.terminal_metrics.shortfall_usd == 100_000.0

    detail = service.rollout(RolloutRequest(scenario=scenario, seed=7))

    assert detail.rollout.failed is True
    assert detail.rollout.monthly_metrics.columns["cash_usd"] == [50_000.0, 0.0, 0.0, 0.0]
    assert detail.rollout.monthly_metrics.columns["public_security_value_usd"] == [150_000.0, 0.0, 0.0, 0.0]
    assert detail.rollout.monthly_metrics.columns["net_worth_usd"] == [200_000.0, 0.0, 0.0, 0.0]


if __name__ == "__main__":
    pytest_bazel.main()
