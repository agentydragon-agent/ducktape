"""Test critic models (scope types, input/output models, discriminated unions).

Tests for models defined in critic/models.py.
"""

from hamcrest import assert_that, equal_to
from props_core.critic.models import CriticSubmitPayload, CriticSuccess


class TestCriticModels:
    """Tests for critic submit and output models."""

    def test_critic_success_variant(self):
        """CriticSuccess should wrap successful critique result."""
        result = CriticSubmitPayload(issues=[], notes_md="All good")
        success = CriticSuccess(result=result)

        assert_that(success.tag, equal_to("success"))
        assert_that(success.result, equal_to(result))
        assert_that(isinstance(success, CriticSuccess))
