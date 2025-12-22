"""Tests for agent_types module."""

from uuid import UUID

from pydantic import TypeAdapter, ValidationError
import pytest

from adgn.props.agent_types import (
    AgentConfig,
    AgentType,
    AllowedExample,
    ClusteringTypeConfig,
    CriticTypeConfig,
    FreeformTypeConfig,
    GraderTypeConfig,
    ImprovementTypeConfig,
    PromptOptimizerTypeConfig,
    TypeConfig,
)
from adgn.props.ids import SnapshotSlug


@pytest.fixture
def type_config_adapter() -> TypeAdapter[TypeConfig]:
    """TypeAdapter for discriminated union parsing."""
    return TypeAdapter(TypeConfig)


class TestTypeConfigDiscriminatedUnion:
    """Tests for TypeConfig discriminated union parsing."""

    @pytest.mark.parametrize(
        ("data", "expected_type"),
        [
            ({"agent_type": "critic", "snapshot_slug": "test/2025-01-01-00", "scope_hash": "y"}, CriticTypeConfig),
            ({"agent_type": "grader", "graded_agent_run_id": "550e8400-e29b-41d4-a716-446655440000"}, GraderTypeConfig),
            ({"agent_type": "freeform"}, FreeformTypeConfig),
            ({"agent_type": "prompt_optimizer", "target_metric": "whole-repo"}, PromptOptimizerTypeConfig),
            ({"agent_type": "clustering", "snapshot_slug": "test/2025-01-01-00"}, ClusteringTypeConfig),
            (
                {
                    "agent_type": "improvement",
                    "baseline_definition_ids": ["critic-v1"],
                    "allowed_examples": [{"snapshot_slug": "test/2025-01-01-00", "scope_hash": "abc"}],
                },
                ImprovementTypeConfig,
            ),
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

    def test_canonical_issues_snapshot_optional(self) -> None:
        """canonical_issues_snapshot defaults to None."""
        config = GraderTypeConfig(graded_agent_run_id=UUID("550e8400-e29b-41d4-a716-446655440000"))
        assert config.canonical_issues_snapshot is None

    def test_canonical_issues_snapshot_accepts_dict(self) -> None:
        """canonical_issues_snapshot accepts dict value."""
        config = GraderTypeConfig(
            graded_agent_run_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
            canonical_issues_snapshot={"true_positives": [], "false_positives": []},
        )
        assert config.canonical_issues_snapshot == {"true_positives": [], "false_positives": []}


class TestPromptOptimizerTypeConfig:
    """Tests for PromptOptimizerTypeConfig behavior."""

    def test_target_metric_required(self) -> None:
        """target_metric is required."""
        with pytest.raises(ValidationError):
            PromptOptimizerTypeConfig()  # type: ignore[call-arg]


class TestImprovementTypeConfig:
    """Tests for ImprovementTypeConfig behavior."""

    def test_valid_construction(self) -> None:
        """ImprovementTypeConfig accepts valid data."""
        config = ImprovementTypeConfig(
            baseline_definition_ids=["critic-v1"],
            allowed_examples=[AllowedExample(snapshot_slug=SnapshotSlug("test/2025-01-01-00"), scope_hash="abc")],
        )
        assert config.baseline_definition_ids == ["critic-v1"]
        assert len(config.allowed_examples) == 1
        assert config.agent_type == AgentType.IMPROVEMENT

    def test_baseline_definition_ids_required_nonempty(self) -> None:
        """baseline_definition_ids must have at least one element."""
        with pytest.raises(ValidationError, match="at least 1"):
            ImprovementTypeConfig(
                baseline_definition_ids=[],
                allowed_examples=[AllowedExample(snapshot_slug=SnapshotSlug("test/2025-01-01-00"), scope_hash="abc")],
            )

    def test_allowed_examples_required_nonempty(self) -> None:
        """allowed_examples must have at least one element."""
        with pytest.raises(ValidationError, match="at least 1"):
            ImprovementTypeConfig(baseline_definition_ids=["critic-v1"], allowed_examples=[])

    def test_both_fields_required(self) -> None:
        """Both baseline_definition_ids and allowed_examples are required."""
        with pytest.raises(ValidationError):
            ImprovementTypeConfig()  # type: ignore[call-arg]

    def test_multiple_definition_ids_allowed(self) -> None:
        """Multiple baseline definition IDs can be provided."""
        config = ImprovementTypeConfig(
            baseline_definition_ids=["critic-v1", "critic-v2", "critic-experimental"],
            allowed_examples=[AllowedExample(snapshot_slug=SnapshotSlug("test/2025-01-01-00"), scope_hash="abc")],
        )
        assert len(config.baseline_definition_ids) == 3

    def test_multiple_examples_allowed(self) -> None:
        """Multiple allowed examples can be provided."""
        config = ImprovementTypeConfig(
            baseline_definition_ids=["critic-v1"],
            allowed_examples=[
                AllowedExample(snapshot_slug=SnapshotSlug("test/2025-01-01-00"), scope_hash="abc"),
                AllowedExample(snapshot_slug=SnapshotSlug("test/2025-01-02-00"), scope_hash="def"),
            ],
        )
        assert len(config.allowed_examples) == 2


class TestAgentConfig:
    """Tests for AgentConfig combining shared fields with type-specific config."""

    def test_basic_construction_with_critic(self) -> None:
        """AgentConfig accepts all required fields with CriticTypeConfig."""
        config = AgentConfig(
            definition_id="critic",
            model="claude-sonnet-4-20250514",
            type_config=CriticTypeConfig(snapshot_slug=SnapshotSlug("test/2025-01-01-00"), scope_hash="abc"),
        )
        assert config.definition_id == "critic"
        assert config.model == "claude-sonnet-4-20250514"
        assert config.parent_agent_run_id is None
        assert isinstance(config.type_config, CriticTypeConfig)

    def test_agent_type_property_returns_critic(self) -> None:
        """agent_type property returns correct type for critic."""
        config = AgentConfig(
            definition_id="critic",
            model="claude-sonnet-4-20250514",
            type_config=CriticTypeConfig(snapshot_slug=SnapshotSlug("test/2025-01-01-00"), scope_hash="abc"),
        )
        assert config.agent_type == AgentType.CRITIC

    def test_agent_type_property_returns_grader(self) -> None:
        """agent_type property returns correct type for grader."""
        config = AgentConfig(
            definition_id="grader",
            model="claude-sonnet-4-20250514",
            type_config=GraderTypeConfig(graded_agent_run_id=UUID("550e8400-e29b-41d4-a716-446655440000")),
        )
        assert config.agent_type == AgentType.GRADER

    def test_agent_type_property_returns_freeform(self) -> None:
        """agent_type property returns correct type for freeform."""
        config = AgentConfig(
            definition_id="custom-sub-agent",
            model="claude-sonnet-4-20250514",
            parent_agent_run_id=UUID("550e8400-e29b-41d4-a716-446655440001"),
            type_config=FreeformTypeConfig(),
        )
        assert config.agent_type == AgentType.FREEFORM

    def test_agent_type_property_returns_clustering(self) -> None:
        """agent_type property returns correct type for clustering."""
        config = AgentConfig(
            definition_id="clustering",
            model="claude-sonnet-4-20250514",
            type_config=ClusteringTypeConfig(snapshot_slug=SnapshotSlug("test/2025-01-01-00")),
        )
        assert config.agent_type == AgentType.CLUSTERING

    def test_parent_agent_run_id_accepts_uuid(self) -> None:
        """parent_agent_run_id accepts UUID for sub-agents."""
        parent_id = UUID("550e8400-e29b-41d4-a716-446655440000")
        config = AgentConfig(
            definition_id="freeform",
            model="claude-sonnet-4-20250514",
            parent_agent_run_id=parent_id,
            type_config=FreeformTypeConfig(),
        )
        assert config.parent_agent_run_id == parent_id

    def test_parent_agent_run_id_coerced_from_string(self) -> None:
        """parent_agent_run_id is coerced from string to UUID."""
        config = AgentConfig(
            definition_id="freeform",
            model="claude-sonnet-4-20250514",
            parent_agent_run_id="550e8400-e29b-41d4-a716-446655440000",  # type: ignore[arg-type]
            type_config=FreeformTypeConfig(),
        )
        assert isinstance(config.parent_agent_run_id, UUID)

    def test_json_serialization_roundtrip(self) -> None:
        """AgentConfig can be serialized to JSON and back."""
        original = AgentConfig(
            definition_id="critic",
            model="claude-sonnet-4-20250514",
            parent_agent_run_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
            type_config=CriticTypeConfig(snapshot_slug=SnapshotSlug("test/2025-01-01-00"), scope_hash="abc"),
        )
        json_str = original.model_dump_json()
        restored = AgentConfig.model_validate_json(json_str)
        assert restored == original
        assert restored.agent_type == AgentType.CRITIC

    def test_definition_id_required(self) -> None:
        """definition_id is required."""
        with pytest.raises(ValidationError):
            AgentConfig(
                model="claude-sonnet-4-20250514",  # type: ignore[call-arg]
                type_config=FreeformTypeConfig(),
            )

    def test_model_required(self) -> None:
        """model is required."""
        with pytest.raises(ValidationError):
            AgentConfig(
                definition_id="test",  # type: ignore[call-arg]
                type_config=FreeformTypeConfig(),
            )

    def test_type_config_required(self) -> None:
        """type_config is required."""
        with pytest.raises(ValidationError):
            AgentConfig(
                definition_id="test",  # type: ignore[call-arg]
                model="claude-sonnet-4-20250514",
            )
