"""Schema-level checks for AugurConfig. Verifies the contract a deployment
must satisfy without exercising any actual file loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel
from pydantic import ValidationError

from augur.app.config import (
    AgentDefinition,
    AugurConfig,
    ConcentratedHoldingConfig,
    ConcentratedHoldingSnapshot,
    FinanceSnapshot,
    LocationConfig,
    PersonalFinanceConfig,
    PropertyCatalogConfig,
    dump_augur_config_yaml,
    load_augur_config,
)
from augur.core.local_regulation import LocalRegulation, LocationId
from augur.core.scenario_set import ActorRole, LiquidityReserveRuleType


def _minimal_config(**overrides: object) -> AugurConfig:
    """Build a placeholder AugurConfig for schema-shape tests. Values are
    intentionally generic — deployments supply their own real values."""
    defaults: dict[str, object] = {
        "agents": (AgentDefinition(actor_id="alpha", label="Alpha", role=ActorRole.PRIMARY_OWNER),),
        "personal_finance": PersonalFinanceConfig(cash_usd=1.0),
        "property_catalog": PropertyCatalogConfig(properties_path="/tmp/properties.json"),
        "snapshot": FinanceSnapshot(as_of_date="2026-05-12"),
    }
    defaults.update(overrides)
    return AugurConfig(**defaults)


def test_minimal_config_validates_with_defaults() -> None:
    config = _minimal_config()

    assert config.agents[0].actor_id == "alpha"
    assert config.location_selection is None
    assert config.minimum_reserve_mode is LiquidityReserveRuleType.PROJECTED_DEFICITS
    assert config.reserve_forward_months == 12
    assert config.default_rollout_samples == 128


def test_concentrated_holdings_round_trip_through_json() -> None:
    config = _minimal_config(
        personal_finance=PersonalFinanceConfig(
            cash_usd=100.0,
            minimum_liquid_reserve_usd=0,
            concentrated_holdings=(
                ConcentratedHoldingConfig(
                    holding_id="example_holding", label="Example Holding", units=10, basis_per_unit_usd=0
                ),
            ),
        )
    )

    reloaded = AugurConfig.model_validate_json(config.model_dump_json())

    holding = reloaded.personal_finance.concentrated_holdings[0]
    assert holding.holding_id == "example_holding"
    assert holding.label == "Example Holding"
    assert holding.units == 10
    assert holding.basis_per_unit_usd == 0


def test_location_selection_accepts_location_strings() -> None:
    config = _minimal_config(location_selection=(LocationId.SAN_FRANCISCO_CA, LocationId.VALLEJO_CA))

    assert config.location_selection == ("san_francisco_ca", "vallejo_ca")


def test_config_can_define_deployment_owned_locations() -> None:
    config = _minimal_config(
        locations=(
            LocationConfig(
                location_id="location_a",
                label="Location A",
                city="Location A",
                state="Fixture",
                home_value_factor_id="location_a_home",
                rent_factor_id="location_a_rent",
                local_regulation=LocalRegulation(
                    property_tax_annual_pct=1.0, notes="Synthetic public fixture location."
                ),
            ),
        ),
        location_selection=("location_a",),
    )

    assert config.locations[0].location_id == "location_a"
    assert config.location_selection == ("location_a",)


def test_at_least_one_agent_required() -> None:
    with pytest.raises(ValidationError, match="Tuple should have at least 1 item"):
        AugurConfig(
            agents=(),
            personal_finance=PersonalFinanceConfig(cash_usd=0),
            property_catalog=PropertyCatalogConfig(properties_path="/tmp/x.json"),
            snapshot=FinanceSnapshot(as_of_date="2026-05-12"),
        )


def test_actor_id_must_be_snake_case() -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        AgentDefinition(actor_id="Alpha", label="Alpha", role=ActorRole.PRIMARY_OWNER)


def test_holding_id_must_be_snake_case() -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        ConcentratedHoldingConfig(holding_id="ExampleHolding", label="Example", units=100)


def test_snapshot_optional_fields_default_to_zero() -> None:
    snapshot = FinanceSnapshot(as_of_date="2026-05-12")
    assert snapshot.cash_usd == 0.0
    assert snapshot.wealthfront_sp500_usd == 0.0
    assert snapshot.notes == ()
    assert snapshot.concentrated_holdings == ()


def test_snapshot_carries_per_holding_fmv() -> None:
    snapshot = FinanceSnapshot(
        as_of_date="2026-05-12",
        concentrated_holdings=(
            ConcentratedHoldingSnapshot(
                holding_id="example_holding", units=10, fmv_usd_per_unit=1.5, valuation_source="placeholder"
            ),
        ),
    )
    assert snapshot.concentrated_holdings[0].fmv_usd_per_unit == 1.5


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _minimal_config(extra_field="nope")


def test_yaml_round_trip_through_dump_and_load(tmp_path) -> None:
    config = _minimal_config(location_selection=(LocationId.SAN_FRANCISCO_CA,), starting_portfolio_usd=100.0)

    path = tmp_path / "config.yaml"
    path.write_text(dump_augur_config_yaml(config), encoding="utf-8")
    reloaded = load_augur_config(path)

    assert reloaded == config


def test_relative_property_catalog_paths_anchor_against_yaml_dir(tmp_path) -> None:
    """ConfigMap mounts put config.yaml + properties.json side-by-side, so the
    yaml stores `properties_path: properties.json` and the loader resolves
    against the yaml's directory."""
    (tmp_path / "properties.json").write_text("[]", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "config.yaml").write_text(
        dump_augur_config_yaml(
            _minimal_config(
                property_catalog=PropertyCatalogConfig(
                    properties_path=Path("properties.json"), asset_dir=Path("assets")
                )
            )
        ),
        encoding="utf-8",
    )

    reloaded = load_augur_config(tmp_path / "config.yaml")

    assert reloaded.property_catalog.properties_path == (tmp_path / "properties.json").resolve()
    assert reloaded.property_catalog.asset_dir == (tmp_path / "assets").resolve()


if __name__ == "__main__":
    pytest_bazel.main()
