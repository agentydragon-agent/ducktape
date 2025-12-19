"""Tests for agent_types module."""

from uuid import UUID

from pydantic import TypeAdapter, ValidationError
import pytest

from adgn.props.agent_types import (
    CriticTypeConfig,
    FreeformTypeConfig,
    GraderTypeConfig,
    PromptOptimizerTypeConfig,
    TypeConfig,
)


@pytest.fixture
def type_config_adapter() -> TypeAdapter[TypeConfig]:
    """TypeAdapter for discriminated union parsing."""
    return TypeAdapter(TypeConfig)


class TestTypeConfigDiscriminatedUnion:
    """Tests for TypeConfig discriminated union parsing."""

    @pytest.mark.parametrize(
        ("data", "expected_type"),
        [
            ({"agent_type": "critic", "snapshot_slug": "x", "scope_hash": "y"}, CriticTypeConfig),
            ({"agent_type": "grader", "graded_agent_run_id": "550e8400-e29b-41d4-a716-446655440000"}, GraderTypeConfig),
            ({"agent_type": "freeform"}, FreeformTypeConfig),
            ({"agent_type": "prompt_optimizer", "target_metric": "whole-repo"}, PromptOptimizerTypeConfig),
        ],
    )
    def test_discriminator_routes_to_correct_type(
        self, type_config_adapter: TypeAdapter[TypeConfig], data: dict, expected_type: type
    ) -> None:
        """Discriminated union routes to correct config type based on agent_type."""
        config = type_config_adapter.validate_python(data)
        assert isinstance(config, expected_type)

    def test_invalid_agent_type_rejected(self, type_config_adapter: TypeAdapter[TypeConfig]) -> None:
        """Unknown agent_type values are rejected."""
        with pytest.raises(ValidationError):
            type_config_adapter.validate_python({"agent_type": "invalid"})


class TestGraderTypeConfig:
    """Tests for GraderTypeConfig behavior."""

    def test_uuid_coercion_from_string(self) -> None:
        """Pydantic coerces string to UUID."""
        config = GraderTypeConfig(
            graded_agent_run_id="550e8400-e29b-41d4-a716-446655440000"  # type: ignore[arg-type]
        )
        assert isinstance(config.graded_agent_run_id, UUID)


class TestPromptOptimizerTypeConfig:
    """Tests for PromptOptimizerTypeConfig behavior."""

    def test_target_metric_required(self) -> None:
        """target_metric is required."""
        with pytest.raises(ValidationError):
            PromptOptimizerTypeConfig()  # type: ignore[call-arg]
