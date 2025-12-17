"""Test critic models (scope types, input/output models, discriminated unions).

Tests for models defined in critic/models.py.
"""

from hamcrest import assert_that, equal_to

from adgn.props.critic.models import CriticInput, CriticSubmitPayload, CriticSuccess
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope

# Note: mock_snapshot_slug fixture is provided in tests/props/conftest.py


class TestCriticModels:
    """Tests for critic input/output models."""

    def test_critic_input_valid(self, mock_snapshot_slug: SnapshotSlug, mock_prompt_sha256: str):
        """CriticInput should accept valid snapshot_slug, scope, and prompt hash."""
        scope_spec = ExplicitFileScope(files=["src/main.py"])
        critic_input = CriticInput(snapshot_slug=mock_snapshot_slug, scope=scope_spec, prompt_sha256=mock_prompt_sha256)

        assert_that(critic_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(critic_input.scope, equal_to(scope_spec))
        assert_that(critic_input.prompt_sha256, equal_to(mock_prompt_sha256))

    def test_critic_input_with_sentinel(self, mock_snapshot_slug: SnapshotSlug, mock_prompt_sha256: str):
        """CriticInput should accept AllFilesScope sentinel."""
        all_files_spec = AllFilesScope()
        critic_input = CriticInput(
            snapshot_slug=mock_snapshot_slug, scope=all_files_spec, prompt_sha256=mock_prompt_sha256
        )

        assert_that(critic_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(critic_input.scope, equal_to(all_files_spec))

    def test_critic_success_variant(self):
        """CriticSuccess should wrap successful critique result."""
        result = CriticSubmitPayload(issues=[], notes_md="All good")
        success = CriticSuccess(result=result)

        assert_that(success.tag, equal_to("success"))
        assert_that(success.result, equal_to(result))
        assert_that(isinstance(success, CriticSuccess))
