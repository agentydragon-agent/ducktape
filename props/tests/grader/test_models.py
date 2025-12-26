"""Test grader models (input/output models, discriminated unions).

Tests for models defined in grader/models.py.
"""

from uuid import uuid4

from hamcrest import assert_that, equal_to

from props.grader.models import GraderInput


class TestGraderModels:
    """Tests for grader input/output models."""

    def test_grader_input_valid(self):
        """GraderInput should accept critic_run_id."""
        critic_run_id = uuid4()
        grader_input = GraderInput(critic_run_id=critic_run_id)

        assert_that(grader_input.critic_run_id, equal_to(critic_run_id))
