"""Test critic models (scope types, input/output models, discriminated unions).

Tests for models defined in critic/models.py.
"""

from pathlib import Path

from hamcrest import assert_that, equal_to
import pytest

from adgn.props.critic.models import ALL_FILES_WITH_ISSUES, CriticInput, CriticSubmitPayload, CriticSuccess
from adgn.props.ids import SnapshotSlug


@pytest.fixture
def mock_snapshot_slug() -> SnapshotSlug:
    """Shared test snapshot slug."""
    return SnapshotSlug("ducktape/2025-11-26-00")


class TestCriticModels:
    """Tests for critic input/output models."""

    def test_critic_input_valid(self, mock_snapshot_slug: SnapshotSlug, mock_prompt_sha256: str):
        """CriticInput should accept valid snapshot_slug, files, and prompt hash."""
        critic_input = CriticInput(
            snapshot_slug=mock_snapshot_slug, files={Path("src/main.py")}, prompt_sha256=mock_prompt_sha256
        )

        assert_that(critic_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(critic_input.files, equal_to({Path("src/main.py")}))
        assert_that(critic_input.prompt_sha256, equal_to(mock_prompt_sha256))

    def test_critic_input_with_sentinel(self, mock_snapshot_slug: SnapshotSlug, mock_prompt_sha256: str):
        """CriticInput should accept ALL_FILES_WITH_ISSUES sentinel."""
        critic_input = CriticInput(
            snapshot_slug=mock_snapshot_slug, files=ALL_FILES_WITH_ISSUES, prompt_sha256=mock_prompt_sha256
        )

        assert_that(critic_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(critic_input.files, equal_to(ALL_FILES_WITH_ISSUES))

    def test_critic_success_variant(self):
        """CriticSuccess should wrap successful critique result."""
        result = CriticSubmitPayload(issues=[], notes_md="All good")
        success = CriticSuccess(result=result)

        assert_that(success.tag, equal_to("success"))
        assert_that(success.result, equal_to(result))
        assert_that(isinstance(success, CriticSuccess))
