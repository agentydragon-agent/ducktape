"""Test critic models (scope types, input/output models, discriminated unions).

Tests for models defined in critic/models.py.
"""

from hamcrest import assert_that, equal_to
import pytest

from adgn.props.critic.models import CriticInput, CriticSubmitPayload, CriticSuccess
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope


@pytest.fixture
def mock_snapshot_slug() -> SnapshotSlug:
    """Shared test snapshot slug."""
    return SnapshotSlug("ducktape/2025-11-26-00")


class TestCriticModels:
    """Tests for critic input/output models."""

    def test_critic_input_valid(self, mock_snapshot_slug: SnapshotSlug, mock_prompt_sha256: str):
        """CriticInput should accept valid snapshot_slug, files, and prompt hash."""
        files_spec = ExplicitFileScope(files=["src/main.py"])
        critic_input = CriticInput(snapshot_slug=mock_snapshot_slug, files=files_spec, prompt_sha256=mock_prompt_sha256)

        assert_that(critic_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(critic_input.files, equal_to(files_spec))
        assert_that(critic_input.prompt_sha256, equal_to(mock_prompt_sha256))

    def test_critic_input_with_sentinel(self, mock_snapshot_slug: SnapshotSlug, mock_prompt_sha256: str):
        """CriticInput should accept AllFilesScope sentinel."""
        all_files_spec = AllFilesScope()
        critic_input = CriticInput(
            snapshot_slug=mock_snapshot_slug, files=all_files_spec, prompt_sha256=mock_prompt_sha256
        )

        assert_that(critic_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(critic_input.files, equal_to(all_files_spec))

    def test_critic_success_variant(self):
        """CriticSuccess should wrap successful critique result."""
        result = CriticSubmitPayload(issues=[], notes_md="All good")
        success = CriticSuccess(result=result)

        assert_that(success.tag, equal_to("success"))
        assert_that(success.result, equal_to(result))
        assert_that(isinstance(success, CriticSuccess))
