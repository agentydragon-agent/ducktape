"""Schema-level checks for Config. Verifies the contract a deployment
must satisfy without exercising any actual file loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel
from pydantic import ValidationError

from augur.api.bootstrap import ActorRole
from augur.api.config import (
    AgentDefinition,
    Config,
    LiquidityReserveRuleType,
    LocationConfig,
    PersonalFinanceConfig,
    PropertyAssetConfig,
    PropertySourceConfig,
    dump_augur_config_yaml,
    load_augur_config,
)
from augur.api.finance import ConcentratedHoldingSnapshot, FinanceSnapshot
from augur.api.local_regulation import LocalRegulation, TaxRegime
from augur.api.portfolio import HoldingPositionConfig, HoldingTaxLotConfig, PortfolioAccountConfig, PortfolioConfig
from augur.model.independent_exogenous import IndependentExogenousProviderConfig


def _minimal_config(**overrides: object) -> Config:
    """Build a placeholder Config for schema-shape tests. Values are
    intentionally generic — deployments supply their own real values."""
    defaults: dict[str, object] = {
        "agents": (AgentDefinition(actor_id="alpha", label="Alpha", role=ActorRole.PRIMARY_OWNER),),
        "personal_finance": PersonalFinanceConfig(),
        "property_source": PropertySourceConfig(properties_path="/tmp/properties.json"),
        "snapshot": FinanceSnapshot(as_of_date="2026-05-12"),
        "default_rollout_samples": 128,
        "max_rollout_samples": 1_000_000,
        "exogenous_provider": IndependentExogenousProviderConfig(),
    }
    defaults.update(overrides)
    return Config(**defaults)


def _fixture_regulation() -> LocalRegulation:
    return LocalRegulation(
        property_tax_regime=TaxRegime.CALIFORNIA_PROP13,
        default_tax_regimes=(
            TaxRegime.CALIFORNIA_PROP13,
            TaxRegime.CALIFORNIA_TRANSFER_TAX,
            TaxRegime.FEDERAL_MORTGAGE_INTEREST,
        ),
        property_tax_annual_pct=1.0,
        notes="Synthetic public fixture location.",
    )


def test_minimal_config_validates_with_explicit_sampling_config() -> None:
    config = _minimal_config()

    assert config.agents[0].actor_id == "alpha"
    assert config.location_selection is None
    assert config.minimum_reserve_mode is LiquidityReserveRuleType.PROJECTED_DEFICITS
    assert config.reserve_forward_months == 12
    assert config.default_rollout_samples == 128
    assert config.max_rollout_samples == 1_000_000


def test_sampling_config_is_required() -> None:
    with pytest.raises(ValidationError, match="default_rollout_samples"):
        _minimal_config(default_rollout_samples=None)
    with pytest.raises(ValidationError, match="max_rollout_samples"):
        _minimal_config(max_rollout_samples=None)


def test_property_source_declares_stable_public_asset_urls() -> None:
    source = PropertySourceConfig(
        properties_path="/tmp/properties.json",
        property_assets=(
            PropertyAssetConfig(
                property_id="location_a_property", image_url="https://cdn.example.com/augur/location-a-hero.jpg"
            ),
            PropertyAssetConfig(
                property_id="location_b_property", image_url="https://cdn.example.com/augur/location-b-hero.jpg"
            ),
        ),
    )

    assert str(source.property_assets[0].image_url) == "https://cdn.example.com/augur/location-a-hero.jpg"
    assert str(source.property_assets[1].image_url) == "https://cdn.example.com/augur/location-b-hero.jpg"


def test_property_asset_requires_image_url() -> None:
    with pytest.raises(ValidationError, match="image_url"):
        PropertyAssetConfig.model_validate({"property_id": "location_a_property"})


def test_property_asset_property_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate property asset property_ids"):
        PropertySourceConfig(
            properties_path="/tmp/properties.json",
            property_assets=(
                PropertyAssetConfig(property_id="location_a_property", image_url="https://cdn.example.com/a.jpg"),
                PropertyAssetConfig(property_id="location_a_property", image_url="https://cdn.example.com/b.jpg"),
            ),
        )


def test_finance_snapshot_holdings_round_trip_through_json() -> None:
    config = _minimal_config(
        snapshot=FinanceSnapshot(
            as_of_date="2026-05-12",
            cash_usd=100.0,
            concentrated_holdings=(
                ConcentratedHoldingSnapshot(
                    holding_id="example_holding", label="Example Holding", units=10, basis_per_unit_usd=0
                ),
            ),
        )
    )

    reloaded = Config.model_validate_json(config.model_dump_json(exclude_computed_fields=True))

    holding = reloaded.snapshot.concentrated_holdings[0]
    assert holding.holding_id == "example_holding"
    assert holding.label == "Example Holding"
    assert holding.units == 10
    assert holding.basis_per_unit_usd == 0


def test_config_carries_tax_lot_accurate_portfolio_schema() -> None:
    config = _minimal_config(
        portfolio=PortfolioConfig(
            accounts=(PortfolioAccountConfig(account_id="taxable_brokerage", owner_agent_id="alpha"),),
            holdings=(
                HoldingPositionConfig(
                    position_id="voo_position",
                    account_id="taxable_brokerage",
                    symbol="VOO",
                    security_kind="etf",
                    value_series_id="voo",
                    unit_value_usd=500.0,
                    lots=(
                        HoldingTaxLotConfig(
                            lot_id="voo_2024_05_12",
                            holding_period_months_at_start=24,
                            quantity=100,
                            cost_basis_usd=30_000,
                        ),
                    ),
                ),
            ),
        )
    )

    reloaded = Config.model_validate_json(config.model_dump_json(exclude_computed_fields=True))

    assert reloaded.portfolio.holdings[0].lots[0].holding_period_months_at_start == 24
    assert reloaded.portfolio.to_initial_lots()[0].purchase_month_index == -24


def test_location_selection_accepts_location_strings() -> None:
    config = _minimal_config(location_selection=("san_francisco_ca", "vallejo_ca"))

    assert config.location_selection == ("san_francisco_ca", "vallejo_ca")


def test_config_can_define_deployment_owned_locations() -> None:
    config = _minimal_config(
        locations=(
            LocationConfig(
                location_id="location_a",
                label="Location A",
                city="Location A",
                state="Fixture",
                local_regulation=_fixture_regulation(),
            ),
        ),
        location_selection=("location_a",),
    )

    assert config.locations[0].location_id == "location_a"
    assert config.location_selection == ("location_a",)


def test_at_least_one_agent_required() -> None:
    with pytest.raises(ValidationError, match="Tuple should have at least 1 item"):
        Config(
            agents=(),
            personal_finance=PersonalFinanceConfig(),
            property_source=PropertySourceConfig(properties_path="/tmp/x.json"),
            snapshot=FinanceSnapshot(as_of_date="2026-05-12"),
            default_rollout_samples=128,
            max_rollout_samples=1_000_000,
            exogenous_provider=IndependentExogenousProviderConfig(),
        )


def test_actor_id_must_be_snake_case() -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        AgentDefinition(actor_id="Alpha", label="Alpha", role=ActorRole.PRIMARY_OWNER)


def test_holding_id_must_be_snake_case() -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        ConcentratedHoldingSnapshot(holding_id="ExampleHolding", label="Example", units=100)


def test_snapshot_optional_fields_default_to_zero() -> None:
    snapshot = FinanceSnapshot(as_of_date="2026-05-12")
    assert snapshot.cash_usd == 0.0
    assert snapshot.wealthfront_sp500_usd == 0.0
    assert snapshot.notes == ()
    assert snapshot.concentrated_holdings == ()


def test_snapshot_carries_per_holding_basis() -> None:
    snapshot = FinanceSnapshot(
        as_of_date="2026-05-12",
        concentrated_holdings=(
            ConcentratedHoldingSnapshot(
                holding_id="example_holding", label="Example Holding", units=10, basis_per_unit_usd=1.5
            ),
        ),
    )
    assert snapshot.concentrated_holdings[0].basis_per_unit_usd == 1.5
    assert snapshot.concentrated_holdings[0].units == 10


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _minimal_config(extra_field="nope")


def test_yaml_round_trip_through_dump_and_load(tmp_path) -> None:
    config = _minimal_config(location_selection=("san_francisco_ca",), starting_portfolio_usd=100.0)

    path = tmp_path / "config.yaml"
    path.write_text(dump_augur_config_yaml(config), encoding="utf-8")
    reloaded = load_augur_config(path)

    assert reloaded == config


def test_relative_property_source_paths_anchor_against_yaml_dir(tmp_path) -> None:
    """ConfigMap mounts put config.yaml + properties.json side-by-side, so the
    yaml stores `properties_path: properties.json` and the loader resolves
    against the yaml's directory."""
    (tmp_path / "properties.json").write_text("[]", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "config.yaml").write_text(
        dump_augur_config_yaml(
            _minimal_config(
                property_source=PropertySourceConfig(
                    properties_path=Path("properties.json"),
                    asset_dir=Path("assets"),
                    property_assets=(
                        PropertyAssetConfig(
                            property_id="location_a_property",
                            image_url="https://cdn.example.com/augur/location-a-hero.jpg",
                        ),
                    ),
                )
            )
        ),
        encoding="utf-8",
    )

    reloaded = load_augur_config(tmp_path / "config.yaml")

    assert reloaded.property_source.properties_path == (tmp_path / "properties.json").resolve()
    assert reloaded.property_source.asset_dir == (tmp_path / "assets").resolve()
    assert (
        str(reloaded.property_source.property_assets[0].image_url)
        == "https://cdn.example.com/augur/location-a-hero.jpg"
    )


if __name__ == "__main__":
    pytest_bazel.main()
