"""Tests for agent_types module."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from adgn.props.agent_types import (
    AgentType,
    CriticTypeConfig,
    FreeformTypeConfig,
    GraderTypeConfig,
    PromptOptimizerTypeConfig,
    TypeConfig,
)
from adgn.props.prompt_optimize.target_metric import TargetMetric


class TestAgentType:
    """Tests for AgentType enum."""

    def test_values(self) -> None:
        """AgentType has expected values."""
        assert AgentType.CRITIC == "critic"
        assert AgentType.GRADER == "grader"
        assert AgentType.PROMPT_OPTIMIZER == "prompt_optimizer"
        assert AgentType.FREEFORM == "freeform"

    def test_is_str_enum(self) -> None:
        """AgentType values work as strings."""
        assert AgentType.CRITIC == "critic"
        assert str(AgentType.CRITIC) == "critic"
        assert f"{AgentType.CRITIC}" == "critic"

    def test_from_string(self) -> None:
        """AgentType can be constructed from string."""
        assert AgentType("critic") == AgentType.CRITIC
        assert AgentType("grader") == AgentType.GRADER


class TestCriticTypeConfig:
    """Tests for CriticTypeConfig."""

    def test_create(self) -> None:
        """Can create CriticTypeConfig with required fields."""
        config = CriticTypeConfig(
            snapshot_slug="myrepo/2025-01-15",
            scope_hash="abc123",
        )
        assert config.agent_type == AgentType.CRITIC
        assert config.snapshot_slug == "myrepo/2025-01-15"
        assert config.scope_hash == "abc123"

    def test_agent_type_is_literal(self) -> None:
        """agent_type defaults to CRITIC and cannot be changed."""
        config = CriticTypeConfig(snapshot_slug="x", scope_hash="y")
        assert config.agent_type == AgentType.CRITIC

    def test_serialization(self) -> None:
        """Config serializes to JSON correctly."""
        config = CriticTypeConfig(snapshot_slug="x", scope_hash="y")
        data = config.model_dump()
        assert data == {
            "agent_type": "critic",
            "snapshot_slug": "x",
            "scope_hash": "y",
        }


class TestGraderTypeConfig:
    """Tests for GraderTypeConfig."""

    def test_create(self) -> None:
        """Can create GraderTypeConfig with required fields."""
        run_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        config = GraderTypeConfig(graded_agent_run_id=run_id)
        assert config.agent_type == AgentType.GRADER
        assert config.graded_agent_run_id == run_id

    def test_uuid_from_string(self) -> None:
        """UUID can be provided as string."""
        config = GraderTypeConfig(
            graded_agent_run_id="550e8400-e29b-41d4-a716-446655440000"  # type: ignore
        )
        assert config.graded_agent_run_id == UUID("550e8400-e29b-41d4-a716-446655440000")


class TestFreeformTypeConfig:
    """Tests for FreeformTypeConfig."""

    def test_create(self) -> None:
        """Can create FreeformTypeConfig with no extra fields."""
        config = FreeformTypeConfig()
        assert config.agent_type == AgentType.FREEFORM

    def test_serialization(self) -> None:
        """Config serializes to just agent_type."""
        config = FreeformTypeConfig()
        assert config.model_dump() == {"agent_type": "freeform"}


class TestPromptOptimizerTypeConfig:
    """Tests for PromptOptimizerTypeConfig."""

    def test_create_whole_repo(self) -> None:
        """Can create with WHOLE_REPO target metric."""
        config = PromptOptimizerTypeConfig(target_metric=TargetMetric.WHOLE_REPO)
        assert config.agent_type == AgentType.PROMPT_OPTIMIZER
        assert config.target_metric == TargetMetric.WHOLE_REPO

    def test_create_targeted(self) -> None:
        """Can create with TARGETED target metric."""
        config = PromptOptimizerTypeConfig(target_metric=TargetMetric.TARGETED)
        assert config.target_metric == TargetMetric.TARGETED

    def test_target_metric_required(self) -> None:
        """target_metric is required."""
        with pytest.raises(ValidationError):
            PromptOptimizerTypeConfig()  # type: ignore


class TestTypeConfigUnion:
    """Tests for TypeConfig discriminated union."""

    def test_discriminator_critic(self) -> None:
        """TypeConfig correctly identifies CriticTypeConfig."""
        from pydantic import TypeAdapter

        adapter = TypeAdapter(TypeConfig)
        config = adapter.validate_python({
            "agent_type": "critic",
            "snapshot_slug": "x",
            "scope_hash": "y",
        })
        assert isinstance(config, CriticTypeConfig)

    def test_discriminator_grader(self) -> None:
        """TypeConfig correctly identifies GraderTypeConfig."""
        from pydantic import TypeAdapter

        adapter = TypeAdapter(TypeConfig)
        config = adapter.validate_python({
            "agent_type": "grader",
            "graded_agent_run_id": "550e8400-e29b-41d4-a716-446655440000",
        })
        assert isinstance(config, GraderTypeConfig)

    def test_discriminator_freeform(self) -> None:
        """TypeConfig correctly identifies FreeformTypeConfig."""
        from pydantic import TypeAdapter

        adapter = TypeAdapter(TypeConfig)
        config = adapter.validate_python({"agent_type": "freeform"})
        assert isinstance(config, FreeformTypeConfig)

    def test_discriminator_prompt_optimizer(self) -> None:
        """TypeConfig correctly identifies PromptOptimizerTypeConfig."""
        from pydantic import TypeAdapter

        adapter = TypeAdapter(TypeConfig)
        config = adapter.validate_python({
            "agent_type": "prompt_optimizer",
            "target_metric": "whole-repo",
        })
        assert isinstance(config, PromptOptimizerTypeConfig)

    def test_invalid_agent_type(self) -> None:
        """Invalid agent_type raises ValidationError."""
        from pydantic import TypeAdapter

        adapter = TypeAdapter(TypeConfig)
        with pytest.raises(ValidationError):
            adapter.validate_python({"agent_type": "invalid"})
