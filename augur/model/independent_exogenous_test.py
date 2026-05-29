from __future__ import annotations

import pytest_bazel
from pydantic import TypeAdapter

from augur.model.exogenous import ExogenousSamplingRequest
from augur.model.exogenous_provider_config import ExogenousProviderConfig
from augur.model.independent_exogenous import IndependentExogenousProviderConfig
from augur.model.series import HomeValueKey, InflationKey, IssuerId, LocationId, RentKey, SP500Key
from augur.product.asset_key import PrivateEquityAssetKey


def _example_config() -> IndependentExogenousProviderConfig:
    return IndependentExogenousProviderConfig.model_validate(
        {
            "type": "independent",
            "series": {
                InflationKey().wire_id: {
                    "kind": "gbm",
                    "initial_value": 1.0,
                    "monthly_log_return_mu": 0.0024906250,
                    "monthly_log_return_sigma": 0.0043301270,
                },
                SP500Key().wire_id: {
                    "kind": "gbm",
                    "initial_value": 1.0,
                    "monthly_log_return_mu": 0.0047333327,
                    "monthly_log_return_sigma": 0.0461880215,
                },
                HomeValueKey(location_id=LocationId("san_francisco_ca")).wire_id: {
                    "kind": "gbm",
                    "initial_value": 1.0,
                    "monthly_log_return_mu": 0.0026498025,
                    "monthly_log_return_sigma": 0.0230940108,
                },
                RentKey(location_id=LocationId("san_francisco_ca")).wire_id: {
                    "kind": "gbm",
                    "initial_value": 1.0,
                    "monthly_log_return_mu": 0.0024625000,
                    "monthly_log_return_sigma": 0.0086602540,
                },
                # PE wire-id entry — the YAML schema still accepts it (legacy back-compat)
                # but the typed boundary routes its month-0 value through metadata only.
                PrivateEquityAssetKey(issuer_id=IssuerId("private_equity_x")).wire_id: {
                    "kind": "gbm",
                    "initial_value": 50.0,
                    "monthly_log_return_mu": 0.0015629326,
                    "monthly_log_return_sigma": 0.1010362971,
                },
            },
        }
    )


def test_independent_model_samples_levels_and_events() -> None:
    model = _example_config().realize_model()

    sampled = model.sample(
        ExogenousSamplingRequest(
            horizon_months=12,
            rollout_seeds=(7, 8),
            required_level_series=frozenset(
                {
                    InflationKey(),
                    SP500Key(),
                    HomeValueKey(location_id=LocationId("san_francisco_ca")),
                    RentKey(location_id=LocationId("san_francisco_ca")),
                }
            ),
        )
    )

    assert set(sampled.levels.get_column("series_id").unique()) == {
        InflationKey().wire_id,
        SP500Key().wire_id,
        HomeValueKey(location_id=LocationId("san_francisco_ca")).wire_id,
        RentKey(location_id=LocationId("san_francisco_ca")).wire_id,
    }
    # IndependentExogenousModel doesn't sample PE channels — the typed PE bundle stays empty.
    assert sampled.private_equity.is_empty()
    assert sampled.metadata["exogenous_model_id"] == "independent_exogenous_model"
    # The PE entry's month-0 initial_value is surfaced via metadata.
    assert sampled.metadata["private_equity_prices_usd"] == {"private_equity_x": 50.0}


def test_independent_provider_config_roundtrips_through_discriminated_union() -> None:
    adapter: TypeAdapter[ExogenousProviderConfig] = TypeAdapter(ExogenousProviderConfig)
    config = adapter.validate_python(_example_config().model_dump())
    assert isinstance(config, IndependentExogenousProviderConfig)
    assert config.realize_model().sample(ExogenousSamplingRequest(horizon_months=3, rollout_seeds=(9,))).metadata[
        "private_equity_prices_usd"
    ] == {"private_equity_x": 50.0}


if __name__ == "__main__":
    pytest_bazel.main()
