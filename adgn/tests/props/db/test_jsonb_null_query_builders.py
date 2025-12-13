"""Comprehensive tests for JSONB null handling in query_builders.

These tests verify that all query functions properly exclude JSONB null values
in addition to SQL NULL. This is critical because PydanticColumn stores Python None
as JSON null ('null'::jsonb), not SQL NULL, and .isnot(None) only excludes SQL NULL.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from adgn.props.db import get_session, query_builders as qb
from adgn.props.db.models import Critique, Snapshot
from adgn.props.ids import SnapshotSlug
from tests.props.conftest import make_critique_payload


class TestRecentGraderResultsJsonbNull:
    """Test recent_grader_results() excludes JSONB null."""

    def test_excludes_jsonb_null(self, test_db, test_prompt_sha):
        """recent_grader_results() excludes grader runs with JSONB null output."""
        critique_id = uuid4()
        grader_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/test-jsonb-null", split="train"))
            session.flush()

            session.add(
                Critique(id=critique_id, snapshot_slug="train/test-jsonb-null", payload=make_critique_payload())
            )
            session.commit()

            # Insert grader run with JSONB null output
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/test-jsonb-null', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        'null'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_id), "cid": str(critique_id)},
            )
            session.commit()

            # Verify JSONB null was set correctly
            check = session.execute(
                text(
                    """
                    SELECT
                        output IS NULL as is_sql_null,
                        output = 'null'::jsonb as is_jsonb_null
                    FROM grader_runs
                    WHERE transcript_id = :tid
                    """
                ),
                {"tid": str(grader_id)},
            ).fetchone()
            assert check is not None
            assert check.is_sql_null is False, "Should be JSONB null, not SQL NULL"
            assert check.is_jsonb_null is True, "Should be JSONB null"

        # Verify query excludes JSONB null
        with get_session() as session:
            result = session.execute(qb.recent_grader_results(limit=100)).fetchall()
            jsonb_null_runs = [r for r in result if r.snapshot_slug == "train/test-jsonb-null"]
            assert len(jsonb_null_runs) == 0, "Should exclude JSONB null rows"

    def test_includes_valid_output(self, test_db, test_prompt_sha):
        """recent_grader_results() includes grader runs with valid output."""
        critique_id = uuid4()
        grader_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/test-valid", split="train"))
            session.flush()

            session.add(Critique(id=critique_id, snapshot_slug="train/test-valid", payload=make_critique_payload()))
            session.commit()

            # Insert grader run with valid output
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/test-valid', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        '{"tag": "success", "recall": 0.5, "canonical_tp_coverage": [], "canonical_fp_coverage": [], "reported_issue_ratios": {"tp": "0.0", "fp": "0.0"}}'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_id), "cid": str(critique_id)},
            )
            session.commit()

        # Verify query includes valid output
        with get_session() as session:
            result = session.execute(qb.recent_grader_results(limit=100)).fetchall()
            valid_runs = [r for r in result if r.snapshot_slug == "train/test-valid"]
            assert len(valid_runs) == 1, "Should include valid output"
            assert valid_runs[0].status == "success"


class TestValidMetricsSelectJsonbNull:
    """Test valid_metrics_select() excludes JSONB null."""

    def test_excludes_jsonb_null(self, test_db, test_prompt_sha):
        """valid_metrics_select() excludes grader runs with JSONB null output."""
        critique_id = uuid4()
        critic_run_id = uuid4()
        grader_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="valid/test-jsonb-null", split="valid"))
            session.flush()

            # Create example and critique
            session.execute(
                text(
                    """
                    INSERT INTO examples (snapshot_slug, files_hash, files)
                    VALUES ('valid/test-jsonb-null', 'test-hash', '[]'::jsonb)
                    """
                )
            )
            session.add(
                Critique(id=critique_id, snapshot_slug="valid/test-jsonb-null", payload=make_critique_payload())
            )
            session.commit()

            # Create critic run
            session.execute(
                text(
                    """
                    INSERT INTO critic_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        files_hash, files, prompt_sha256
                    ) VALUES (
                        :crid, gen_random_uuid(), 'valid/test-jsonb-null', 'test-model', :cid,
                        'test-hash', '[]'::jsonb, :sha
                    )
                    """
                ),
                {"crid": str(critic_run_id), "cid": str(critique_id), "sha": test_prompt_sha},
            )
            session.commit()

            # Insert grader run with JSONB null output
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'valid/test-jsonb-null', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        'null'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_id), "cid": str(critique_id)},
            )
            session.commit()

        # Verify query excludes JSONB null
        with get_session() as session:
            result = session.execute(qb.valid_metrics_select()).fetchall()
            jsonb_null_runs = [r for r in result if r.snapshot_slug == "valid/test-jsonb-null"]
            assert len(jsonb_null_runs) == 0, "Should exclude JSONB null rows"


class TestLinkGraderToPromptJsonbNull:
    """Test link_grader_to_prompt() excludes JSONB null."""

    def test_excludes_jsonb_null(self, test_db, test_prompt_sha):
        """link_grader_to_prompt() excludes grader runs with JSONB null output."""
        critique_id = uuid4()
        critic_run_id = uuid4()
        grader_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/test-link-jsonb-null", split="train"))
            session.flush()

            session.add(
                Critique(id=critique_id, snapshot_slug="train/test-link-jsonb-null", payload=make_critique_payload())
            )
            session.commit()

            # Create critic run
            session.execute(
                text(
                    """
                    INSERT INTO critic_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        files_hash, files, prompt_sha256
                    ) VALUES (
                        :crid, gen_random_uuid(), 'train/test-link-jsonb-null', 'test-model', :cid,
                        'test-hash', '[]'::jsonb, :sha
                    )
                    """
                ),
                {"crid": str(critic_run_id), "cid": str(critique_id), "sha": test_prompt_sha},
            )
            session.commit()

            # Insert grader run with JSONB null output
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/test-link-jsonb-null', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        'null'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_id), "cid": str(critique_id)},
            )
            session.commit()

        # Verify query excludes JSONB null
        with get_session() as session:
            result = session.execute(
                qb.link_grader_to_prompt(SnapshotSlug("train/test-link-jsonb-null"), limit=10)
            ).fetchall()
            assert len(result) == 0, "Should exclude JSONB null rows"


class TestGraderRunsByScopeTrainJsonbNull:
    """Test grader_runs_by_scope_train() excludes JSONB null."""

    def test_excludes_jsonb_null(self, test_db, test_prompt_sha):
        """grader_runs_by_scope_train() excludes grader runs with JSONB null output."""
        critique_id = uuid4()
        critic_run_id = uuid4()
        grader_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/test-scope-jsonb-null", split="train"))
            session.flush()

            # Create example
            session.execute(
                text(
                    """
                    INSERT INTO examples (snapshot_slug, files_hash, files)
                    VALUES ('train/test-scope-jsonb-null', 'test-hash', '["foo.py"]'::jsonb)
                    """
                )
            )

            session.add(
                Critique(id=critique_id, snapshot_slug="train/test-scope-jsonb-null", payload=make_critique_payload())
            )
            session.commit()

            # Create critic run
            session.execute(
                text(
                    """
                    INSERT INTO critic_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        files_hash, files, prompt_sha256
                    ) VALUES (
                        :crid, gen_random_uuid(), 'train/test-scope-jsonb-null', 'test-model', :cid,
                        'test-hash', '["foo.py"]'::jsonb, :sha
                    )
                    """
                ),
                {"crid": str(critic_run_id), "cid": str(critique_id), "sha": test_prompt_sha},
            )
            session.commit()

            # Insert grader run with JSONB null output
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/test-scope-jsonb-null', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        'null'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_id), "cid": str(critique_id)},
            )
            session.commit()

        # Verify query excludes JSONB null
        with get_session() as session:
            result = session.execute(qb.grader_runs_by_scope_train(limit=100)).fetchall()
            jsonb_null_runs = [r for r in result if r.snapshot_slug == "train/test-scope-jsonb-null"]
            assert len(jsonb_null_runs) == 0, "Should exclude JSONB null rows"


class TestHelperFunction:
    """Test the _exclude_jsonb_null helper function."""

    def test_exclude_jsonb_null_works_in_query(self, test_db, test_prompt_sha):
        """_exclude_jsonb_null() works correctly in a real query."""
        from sqlalchemy import select

        from adgn.props.db.models import GraderRun
        from adgn.props.db.query_builders import _exclude_jsonb_null

        critique_id = uuid4()
        grader_jsonb_null_id = uuid4()
        grader_valid_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/test-helper", split="train"))
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
