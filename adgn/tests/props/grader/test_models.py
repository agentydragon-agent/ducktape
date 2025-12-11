"""Test grader models (input/output models, discriminated unions).

Tests for models defined in grader/models.py.
"""

from uuid import uuid4

from hamcrest import assert_that, equal_to

from adgn.props.grader.models import GraderInput
from adgn.props.ids import SnapshotSlug

# Note: mock_snapshot_slug fixture is provided in tests/props/conftest.py


class TestGraderModels:
    """Tests for grader input/output models."""

    def test_grader_input_valid(self, mock_snapshot_slug: SnapshotSlug):
        """GraderInput should accept snapshot_slug and critique_id."""
        critique_id = uuid4()
        grader_input = GraderInput(snapshot_slug=mock_snapshot_slug, critique_id=critique_id)

        assert_that(grader_input.snapshot_slug, equal_to(mock_snapshot_slug))
        assert_that(grader_input.critique_id, equal_to(critique_id))
