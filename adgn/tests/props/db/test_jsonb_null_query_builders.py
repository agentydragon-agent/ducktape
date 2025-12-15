"""Comprehensive tests for JSONB null handling in query_builders.

These tests verify that all query functions properly exclude JSONB null values
in addition to SQL NULL. This is critical because PydanticColumn stores Python None
as JSON null ('null'::jsonb), not SQL NULL, and .isnot(None) only excludes SQL NULL.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select, text

from adgn.props.db import get_session
from adgn.props.db.models import Critique, GraderRun, Snapshot
from adgn.props.db.query_builders import _exclude_jsonb_null
from adgn.props.models.snapshot import LocalSource
from tests.props.conftest import make_critique_payload


class TestHelperFunction:
    """Test the _exclude_jsonb_null helper function."""

    def test_exclude_jsonb_null_works_in_query(self, test_db, test_prompt_sha):
        """_exclude_jsonb_null() works correctly in a real query."""
        critique_id = uuid4()
        grader_jsonb_null_id = uuid4()
        grader_valid_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/test-helper", split="train", source=LocalSource(vcs="local", root=".")))
            session.flush()

            session.add(Critique(id=critique_id, snapshot_slug="train/test-helper", payload=make_critique_payload()))
            session.commit()

            # Insert one with JSONB null
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/test-helper', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        'null'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_jsonb_null_id), "cid": str(critique_id)},
            )

            # Insert one with valid output
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/test-helper', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        '{"tag": "success"}'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_valid_id), "cid": str(critique_id)},
            )
            session.commit()

        # Query with both filters
        with get_session() as session:
            query = (
                select(GraderRun.transcript_id)
                .where(GraderRun.snapshot_slug == "train/test-helper")
                .where(GraderRun.output.isnot(None))  # Excludes SQL NULL
                .where(_exclude_jsonb_null(GraderRun.output))  # Excludes JSON null
            )
            result = session.execute(query).scalars().all()

            # Should only get the valid one
            assert len(result) == 1, "Should exclude JSONB null, include valid"
            assert str(result[0]) == str(grader_valid_id), "Should get the valid grader run"
