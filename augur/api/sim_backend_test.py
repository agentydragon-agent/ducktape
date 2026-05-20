from __future__ import annotations

from typing import NoReturn

import pytest_bazel

from augur.api.backend import AugurBackend, AugurBackendRuntimeConfig
from augur.api.config import load_augur_config
from augur.core.casing import plain_json
from augur.core.market_bundle import RequiredMarketKeys
from augur.core.scenario_set import MarketRequest, RolloutStatusType
from augur.model.simple_market import SimpleMarketModel
from util.bazel.runfiles import get_required_path


class FailingCoreMarketProvider:
    def sample_market_bundle(
        self,
        *,
        rollout_count: int,
        horizon_months: int,
        seed: int,
        market_request: MarketRequest,
        required_keys: RequiredMarketKeys,
    ) -> NoReturn:
        raise AssertionError("sim backend should not call the core market provider")


def test_sim_backend_flag_runs_joint_model_and_materializes_graph_tables() -> None:
    backend = AugurBackend(
        augur_config=load_augur_config(get_required_path("_main/augur/api/testdata/config.yaml")),
        runtime_config=AugurBackendRuntimeConfig(
            market_bundle_provider=FailingCoreMarketProvider(),
            default_rollout_samples=3,
            max_rollout_samples=3,
            market_model=SimpleMarketModel(current_private_equity_price_usd=25.0),
            execution_engine="sim",
        ),
    )

    response = backend.run_scenario_set_for_request_body(
        {
            "scenario_set_id": "sim_backend_cutover_smoke",
            "title": "Sim backend cutover smoke",
            "market_request": {"market_model_id": "simple", "rollout_count": 3, "horizon_months": 3, "seed": 11},
            "scenarios": [
                {
                    "scenario_id": "sp500_spend",
                    "label": "SP500 spend",
                    "actors": [{"actor_id": "agent_a", "label": "Agent A", "role": "primary_owner"}],
                    "initial_balance_sheet": {
                        "accounts": [
                            {
                                "account_id": "checking",
                                "account_type": "checking",
                                "owner_actor_id": "agent_a",
                                "balance_usd": 0.0,
                            }
                        ],
                        "assets": [
                            {
                                "asset_id": "wealthfront_sp500",
                                "asset_type": "generic_sp500_stock",
                                "owner_actor_id": "agent_a",
                                "value_usd": 1000.0,
                                "cost_basis_usd": 700.0,
                            }
                        ],
                    },
                    "policies": [
                        {
                            "policy_id": "monthly_spend",
                            "policy_type": "monthly_spend",
                            "actor_id": "agent_a",
                            "monthly_spend_usd": 100.0,
                        },
                        {
                            "policy_id": "sell_sp500",
                            "policy_type": "checking_floor_sell_public_stock",
                            "actor_id": "agent_a",
                            "floor_usd": 0.0,
                            "sale_amount_usd": 0.0,
                        },
                    ],
                }
            ],
        }
    )

    assert response.market_metadata is not None
    assert response.market_metadata["market_model_id"] == "simple_market_model"
    assert response.market_metadata["source_metadata"]["level_anchors"] == {"sp500": 500.0}
    result = response.scenario_results[0]
    assert result.monthly_columns is not None
    assert result.monthly_columns.row_count == 12
    assert result.terminal_columns is not None
    assert result.terminal_columns.row_count == 3
    assert result.metric_fan_columns["net_worth_usd"].row_count == 4
    assert "p05" in result.metric_fan_columns["net_worth_usd"].columns
    assert "p95" in result.metric_fan_columns["net_worth_usd"].columns
    assert sum(result.monthly_columns.columns["generic_sp500_sale_usd"]) > 0
    assert [status.status for status in result.rollout_statuses] == [RolloutStatusType.ACTIVE] * 3

    payload = plain_json(response)
    scenario_payload = payload["scenario_results"][0]
    assert scenario_payload["metric_fan_columns"]["net_worth_usd"]["row_count"] == 4
    assert scenario_payload["monthly_columns"]["row_count"] == 12


def test_sim_backend_flag_accepts_catalog_defaulted_property_selection() -> None:
    backend = AugurBackend(
        augur_config=load_augur_config(get_required_path("_main/augur/api/testdata/config.yaml")),
        runtime_config=AugurBackendRuntimeConfig(
            market_bundle_provider=FailingCoreMarketProvider(),
            default_rollout_samples=3,
            max_rollout_samples=3,
            market_model=SimpleMarketModel(current_private_equity_price_usd=25.0),
            execution_engine="sim",
        ),
    )

    response = backend.run_scenario_set_for_request_body(
        {
            "scenario_set_id": "sim_backend_property_smoke",
            "title": "Sim backend property smoke",
            "market_request": {"market_model_id": "simple", "rollout_count": 3, "horizon_months": 3, "seed": 11},
            "scenarios": [
                {
                    "scenario_id": "buy_catalog_property",
                    "label": "Buy catalog property",
                    "actors": [{"actor_id": "agent_a", "label": "Agent A", "role": "primary_owner"}],
                    "property_selection": {"property_id": "location_a_property"},
                    "financing": {"financing_mode": "fixed_30", "down_payment_pct": 20, "mortgage_rate_pct": 6.5},
                    "initial_balance_sheet": {
                        "accounts": [
                            {
                                "account_id": "checking",
                                "account_type": "checking",
                                "owner_actor_id": "agent_a",
                                "balance_usd": 300_000.0,
                            }
                        ],
                        "assets": [],
                    },
                }
            ],
        }
    )

    result = response.scenario_results[0]
    assert result.summary.property_id == "location_a_property"
    assert result.summary.location_id == "location_a"
    assert result.terminal_columns is not None
    assert result.terminal_columns.row_count == 3


if __name__ == "__main__":
    pytest_bazel.main()
