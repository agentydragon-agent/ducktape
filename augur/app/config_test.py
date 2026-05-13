"""Schema-level checks for AugurConfig. Verifies the contract a deployment
must satisfy without exercising any actual file loading."""

from __future__ import annotations

import pytest
import pytest_bazel
from pydantic import ValidationError

from augur.app.config import (
    AgentDefinition,
    AugurConfig,
    ConcentratedHoldingConfig,
    ConcentratedHoldingSnapshot,
    FinanceSnapshot,
    PersonalFinanceConfig,
    PropertyCatalogConfig,
)
from augur.core.local_regulation import LocationId
from augur.core.scenario_set import ActorRole


def _minimal_config(**overrides: object) -> AugurConfig:
    defaults: dict[str, object] = {
        "agents": (AgentDefinition(actor_id="rai", label="Rai", role=ActorRole.PRIMARY_OWNER),),
        "personal_finance": PersonalFinanceConfig(cash_usd=10_000),
        "property_catalog": PropertyCatalogConfig(properties_path="/tmp/properties.json"),
        "snapshot": FinanceSnapshot(as_of_date="2026-05-12"),
    }
    defaults.update(overrides)
    return AugurConfig(**defaults)  # type: ignore[arg-type]


def test_minimal_config_validates_with_defaults() -> None:
    config = _minimal_config()

    assert config.agents[0].actor_id == "rai"
    assert config.location_selection is None
    assert config.private_equity_sale_mode == "liquidity_only"
    assert config.minimum_reserve_mode == "projected_deficits"
    assert config.reserve_forward_months == 12
    assert config.default_rollout_samples == 128


def test_concentrated_holdings_round_trip_through_json() -> None:
    config = _minimal_config(
        personal_finance=PersonalFinanceConfig(
            cash_usd=21_000,
            minimum_liquid_reserve_usd=0,
            concentrated_holdings=(
                ConcentratedHoldingConfig(
                    holding_id="openai",
                    label="OpenAI",
                    units=23_553,
                    basis_per_unit_usd=0,
                    tax_rate_pct=35,
                    target_max_net_worth_pct=60,
                ),
            ),
        )
    )

    reloaded = AugurConfig.model_validate_json(config.model_dump_json())

    holding = reloaded.personal_finance.concentrated_holdings[0]
    assert holding.holding_id == "openai"
    assert holding.label == "OpenAI"
    assert holding.units == 23_553
    assert holding.tax_rate_pct == 35


def test_location_selection_accepts_known_ids() -> None:
    config = _minimal_config(location_selection=(LocationId.SAN_FRANCISCO_CA, LocationId.VALLEJO_CA))

    assert config.location_selection == (LocationId.SAN_FRANCISCO_CA, LocationId.VALLEJO_CA)


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
        AgentDefinition(actor_id="Rai", label="Rai", role=ActorRole.PRIMARY_OWNER)


def test_holding_id_must_be_snake_case() -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        ConcentratedHoldingConfig(holding_id="OpenAI", label="OpenAI", units=100)


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
                holding_id="openai", units=23_553, fmv_usd_per_unit=687.69, valuation_source="Shareworks FMV"
            ),
        ),
    )
    assert snapshot.concentrated_holdings[0].fmv_usd_per_unit == 687.69


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _minimal_config(extra_field="nope")  # type: ignore[call-arg]


if __name__ == "__main__":
    pytest_bazel.main()
