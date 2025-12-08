"""Unit tests for agent SQL query builders.

Tests verify:
1. Query builders execute successfully via SQLAlchemy
2. Return expected data shapes and values

This tests the single source of truth: query_builders.py functions are executed
directly in tests, and the same query builders are compiled to SQL for j2 templates.

Does NOT test:
- RLS policies (covered in test_db_integration.py)
- Docker integration (covered in test_prompt_optimizer_integration.py)
- Database setup/teardown (uses existing test_db fixture)
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from adgn.props.critic.models import CriticSubmitPayload, ReportedIssue
from adgn.props.db import get_session, query_builders as qb
from adgn.props.db.models import (
    CriticRun,
    CriticScopeDB,
    Critique,
    Event,
    FalsePositive,
    GraderRun,
    Prompt,
    Snapshot,
    TruePositive,
)
from adgn.props.ids import SnapshotSlug
from adgn.props.models.true_positive import FileOccurrence, Occurrence
from tests.conftest import EMPTY_CANONICAL_ISSUES_SNAPSHOT
from tests.props.conftest import TEST_FILES_HASH, TEST_FILES_LIST, make_grader_output

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@pytest.fixture
def query_test_data(test_db):
    """Populate database with simple test data for query validation.

    Creates:
    - 3 train snapshots, 2 valid snapshots
    - 2 true positives and 1 false positive for train snapshots
    - 1 prompt
    - 2 critiques (for 2 different train snapshots)
    - 2 critic runs (linked to critiques)
    - 3 grader runs (2 train, 1 valid)
    - Event records (tool_call and function_call_output events)
    """
    with get_session() as session:
        # Create snapshots
        snapshots = [
            Snapshot(slug="train/spec-a", split="train"),
            Snapshot(slug="train/spec-b", split="train"),
            Snapshot(slug="train/spec-c", split="train"),
            Snapshot(slug="valid/spec-a", split="valid"),
            Snapshot(slug="valid/spec-b", split="valid"),
        ]
        for spec in snapshots:
            session.merge(spec)

        session.flush()

        # Create true positives and false positives
        true_positives = [
            TruePositive(
                snapshot_slug=SnapshotSlug("train/spec-a"),
                tp_id="tp-001",
                rationale="Test true positive 1",
                occurrences=[
                    {
                        "files": {"file1.py": [{"start_line": 1, "end_line": 10}]},
                        "note": "First occurrence",
                        "expect_caught_from": [frozenset({"file1.py"})],
                    }
                ],
            ),
            TruePositive(
                snapshot_slug=SnapshotSlug("train/spec-b"),
                tp_id="tp-002",
                rationale="Test true positive 2",
                occurrences=[
                    {
                        "files": {"file2.py": [{"start_line": 5, "end_line": 15}]},
                        "note": "Second occurrence",
                        "expect_caught_from": [frozenset({"file2.py"})],
                    }
                ],
            ),
        ]
        for tp in true_positives:
            session.merge(tp)

        false_positives = [
            FalsePositive(
                snapshot_slug=SnapshotSlug("train/spec-a"),
                fp_id="fp-001",
                rationale="Test false positive 1",
                occurrences=[
                    {
                        "files": {"file3.py": [{"start_line": 20, "end_line": 30}]},
                        "note": "FP occurrence",
                        "relevant_files": ["file3.py"],
                    }
                ],
            )
        ]
        for fp in false_positives:
            session.merge(fp)

        # Create TP for valid/spec-a (required for snapshot_files_with_issues view)
        # TEST_FILES_LIST is ["test.py"]
        tp_valid = TruePositive(
            snapshot_slug=SnapshotSlug("valid/spec-a"),
            tp_id="tp-valid-001",
            rationale="Test issue for valid snapshot",
            occurrences=[{"files": {"test.py": None}, "expect_caught_from": [frozenset({Path("test.py")})]}],
        )
        session.merge(tp_valid)

        # Create prompt
        prompt = Prompt(prompt_sha256="a" * 64, prompt_text="Test prompt for query validation")
        session.merge(prompt)

        session.flush()

        # Create critiques (train and valid)
        critique_a_id = uuid4()
        critique_b_id = uuid4()
        critique_valid_id = uuid4()

        critiques = [
            Critique(
                id=critique_a_id,
                snapshot_slug="train/spec-a",
                payload=CriticSubmitPayload(
                    issues=[
                        ReportedIssue(
                            id="issue-1",
                            rationale="Test issue",
                            occurrences=[
                                Occurrence(files=[FileOccurrence(path=Path("file1.py"), ranges=None)], note=None)
                            ],
                        )
                    ],
                    notes_md="",
                ),
            ),
            Critique(
                id=critique_b_id,
                snapshot_slug="train/spec-b",
                payload=CriticSubmitPayload(
                    issues=[
                        ReportedIssue(
                            id="issue-2",
                            rationale="Another issue",
                            occurrences=[
                                Occurrence(files=[FileOccurrence(path=Path("file2.py"), ranges=None)], note=None)
                            ],
                        )
                    ],
                    notes_md="",
                ),
            ),
            Critique(
                id=critique_valid_id,
                snapshot_slug="valid/spec-a",
                payload=CriticSubmitPayload(
                    issues=[
                        ReportedIssue(
                            id="issue-3",
                            rationale="Valid issue",
                            occurrences=[
                                Occurrence(files=[FileOccurrence(path=Path("test.py"), ranges=None)], note=None)
                            ],
                        )
                    ],
                    notes_md="",
                ),
            ),
        ]
        for critique in critiques:
            session.merge(critique)

        session.flush()

        # Create critic runs (linked to critiques, including valid/spec-a)
        critic_runs = [
            CriticRun(
                transcript_id=uuid4(),
                prompt_sha256="a" * 64,
                snapshot_slug="train/spec-a",
                model="test-model",
                critique_id=critique_a_id,
                files=TEST_FILES_LIST,
                files_hash=TEST_FILES_HASH,
                output={"tag": "success"},
            ),
            CriticRun(
                transcript_id=uuid4(),
                prompt_sha256="a" * 64,
                snapshot_slug="train/spec-b",
                model="test-model",
                critique_id=critique_b_id,
                files=TEST_FILES_LIST,
                files_hash=TEST_FILES_HASH,
                output={"tag": "success"},
            ),
            CriticRun(
                transcript_id=uuid4(),
                prompt_sha256="a" * 64,
                snapshot_slug="valid/spec-a",
                model="test-model",
                critique_id=critique_valid_id,
                files=TEST_FILES_LIST,
                files_hash=TEST_FILES_HASH,
                output={"tag": "success"},
            ),
        ]
        for run in critic_runs:
            session.add(run)

        session.flush()

        # Create grader runs (2 train, 1 valid)
        # Output built from GraderOutput Pydantic model via make_grader_output()
        grader_runs = [
            GraderRun(
                transcript_id=uuid4(),
                snapshot_slug="train/spec-a",
                model="test-model-1",
                critique_id=critique_a_id,
                canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
                output=make_grader_output(
                    tp_count=4, fp_count=1, recall=0.8, tp_ratio=0.8, fp_ratio=0.1, summary="Test grading spec-a"
                ),
            ),
            GraderRun(
                transcript_id=uuid4(),
                snapshot_slug="train/spec-b",
                model="test-model-1",
                critique_id=critique_b_id,
                canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
                output=make_grader_output(
                    tp_count=9, fp_count=2, recall=0.9, tp_ratio=0.85, fp_ratio=0.1, summary="Test grading spec-b"
                ),
            ),
            GraderRun(
                transcript_id=uuid4(),
                snapshot_slug="valid/spec-a",
                model="test-model-2",
                critique_id=critique_valid_id,
                canonical_issues_snapshot=EMPTY_CANONICAL_ISSUES_SNAPSHOT,
                output=make_grader_output(
                    tp_count=3,
                    fp_count=0,
                    recall=0.75,
                    tp_ratio=0.95,
                    fp_ratio=0.03,
                    summary="Test grading valid/spec-a",
                ),
            ),
        ]
        for grader_run in grader_runs:
            session.add(grader_run)

        session.flush()

        # Create event records for one transcript_id
        test_transcript_id = critic_runs[0].transcript_id
        now = datetime.now()
        event_specs = [
            (0, "tool_call", {"name": "Read", "args_json": '{"file_path": "test.py"}', "call_id": "call-1"}),
            (1, "function_call_output", {"call_id": "call-1", "result": {"isError": False}}),
            (2, "tool_call", {"name": "Grep", "args_json": '{"pattern": "foo"}', "call_id": "call-2"}),
            (3, "function_call_output", {"call_id": "call-2", "result": {"isError": True}}),
        ]
        for seq_num, evt_type, payload in event_specs:
            session.add(
                Event(
                    transcript_id=test_transcript_id,
                    sequence_num=seq_num,
                    event_type=evt_type,
                    timestamp=now,
                    payload=payload,
                )
            )

        session.commit()
        return test_transcript_id  # Return for use in event query tests


class TestQueryBuilders:
    """Test query builders execute and return expected data."""

    def test_list_train_snapshots(self, query_test_data):
        """list_train_snapshots() returns train snapshots in order."""
        with get_session() as session:
            result = session.execute(qb.list_train_snapshots()).fetchall()

            # Should have 3 train snapshots
            assert len(result) == 3

            # Check first row has expected columns and values
            assert result[0].slug == "train/spec-a"
            assert result[0].split == "train"

            # Check ordering
            slugs = [row.slug for row in result]
            assert slugs == ["train/spec-a", "train/spec-b", "train/spec-c"]

    def test_list_train_true_positives(self, query_test_data):
        """list_train_true_positives() returns all TPs for train split."""
        with get_session() as session:
            result = session.execute(qb.list_train_true_positives()).fetchall()

            # Should have 2 train true positives
            assert len(result) == 2

            # Check structure
            assert result[0].snapshot_slug in ("train/spec-a", "train/spec-b")
            assert result[0].tp_id in ("tp-001", "tp-002")
            assert result[0].rationale is not None

    def test_list_train_false_positives(self, query_test_data):
        """list_train_false_positives() returns all FPs for train split."""
        with get_session() as session:
            result = session.execute(qb.list_train_false_positives()).fetchall()

            # Should have 1 train false positive
            assert len(result) == 1

            # Check structure
            assert result[0].snapshot_slug == "train/spec-a"
            assert result[0].fp_id == "fp-001"
            assert result[0].rationale == "Test false positive 1"

    def test_count_issues_by_snapshot(self, query_test_data):
        """count_issues_by_snapshot() returns TP/FP counts per snapshot."""
        with get_session() as session:
            result = session.execute(qb.count_issues_by_snapshot(split="train")).fetchall()

            # Should have 3 train snapshots
            assert len(result) == 3

            # Find spec-a (has 1 TP and 1 FP)
            spec_a_rows = [row for row in result if row.snapshot_slug == "train/spec-a"]
            assert len(spec_a_rows) == 1
            assert spec_a_rows[0].tp_count == 1
            assert spec_a_rows[0].fp_count == 1

            # Find spec-b (has 1 TP, 0 FP)
            spec_b_rows = [row for row in result if row.snapshot_slug == "train/spec-b"]
            assert len(spec_b_rows) == 1
            assert spec_b_rows[0].tp_count == 1
            assert spec_b_rows[0].fp_count == 0

            # Find spec-c (has 0 TP, 0 FP)
            spec_c_rows = [row for row in result if row.snapshot_slug == "train/spec-c"]
            assert len(spec_c_rows) == 1
            assert spec_c_rows[0].tp_count == 0
            assert spec_c_rows[0].fp_count == 0

    def test_list_true_positives_for_snapshot(self, query_test_data):
        """list_true_positives_for_snapshot() returns TPs for specific snapshot."""
        with get_session() as session:
            result = session.execute(qb.list_true_positives_for_snapshot(SnapshotSlug("train/spec-a"))).fetchall()

            # Should have 1 TP
            assert len(result) == 1
            assert result[0].tp_id == "tp-001"
            assert result[0].rationale == "Test true positive 1"
            assert len(result[0].occurrences) == 1

    def test_list_false_positives_for_snapshot(self, query_test_data):
        """list_false_positives_for_snapshot() returns FPs for specific snapshot."""
        with get_session() as session:
            result = session.execute(qb.list_false_positives_for_snapshot(SnapshotSlug("train/spec-a"))).fetchall()

            # Should have 1 FP
            assert len(result) == 1
            assert result[0].fp_id == "fp-001"
            assert result[0].rationale == "Test false positive 1"
            assert len(result[0].occurrences) == 1

    def test_recent_grader_results(self, query_test_data):
        """recent_grader_results() returns train grader runs with metrics.

        Query returns columns matching GraderOutput Pydantic schema:
        - recall: direct field
        - canonical_tp_count: array length of canonical_tp_coverage
        - canonical_fp_count: array length of canonical_fp_coverage
        - reported_tp_ratio, reported_fp_ratio: from reported_issue_ratios
        """
        with get_session() as session:
            result = session.execute(qb.recent_grader_results(limit=10)).fetchall()

            # Should have at least 2 train grader runs (query returns max 10)
            assert len(result) >= 2
            assert len(result) <= 10

            # Check first row has expected columns
            row = result[0]
            assert row.snapshot_slug in ("train/spec-a", "train/spec-b")
            assert row.recall in ("0.8", "0.9")  # JSONB returns strings
            # canonical_tp_count: spec-a has 4 TPs, spec-b has 9 TPs
            assert row.canonical_tp_count in (4, 9)
            # canonical_fp_count: spec-a has 1 FP, spec-b has 2 FPs
            assert row.canonical_fp_count in (1, 2)
            # reported_tp_ratio from reported_issue_ratios.tp
            assert row.reported_tp_ratio in ("0.8", "0.85")
            assert row.model == "test-model-1"
            assert row.transcript_id is not None
            assert row.created_at is not None

    def test_valid_aggregates_view(self, query_test_data):
        """valid_aggregates_view() computes statistics for valid split."""
        with get_session() as session:
            result = session.execute(qb.valid_aggregates_view()).fetchall()

            # Should have at least 1 row
            assert len(result) >= 1

            # Check aggregate columns (find our test-model-2 row)
            test_model_2_rows = [row for row in result if row.grader_model == "test-model-2"]
            assert len(test_model_2_rows) >= 1

            row = test_model_2_rows[0]
            # Use approximate comparison for floats
            assert abs(row.avg_recall - 0.75) < 0.01
            # Note: precision is not in the view (user requested only recall)
            assert row.snapshot_count >= 1  # At least 1 distinct snapshot
            assert row.run_count >= 1  # At least 1 total valid grader run

    def test_link_grader_to_prompt(self, query_test_data):
        """link_grader_to_prompt() traces grader back to prompt text."""
        with get_session() as session:
            result = session.execute(qb.link_grader_to_prompt(SnapshotSlug("train/spec-a"), limit=1)).fetchall()

            # Should have 1 result
            assert len(result) == 1

            # Check all join columns are present
            row = result[0]
            assert row.grader_run_id is not None
            assert row.snapshot_slug == "train/spec-a"
            assert row.recall == "0.8"
            assert row.critique_id is not None
            assert row.critic_run_id is not None
            assert row.prompt_sha256 == "a" * 64
            assert row.prompt_text == "Test prompt for query validation"

    def test_critiques_for_snapshot(self, query_test_data):
        """critiques_for_snapshot() returns critiques for a specific snapshot."""
        with get_session() as session:
            result = session.execute(qb.critiques_for_snapshot(SnapshotSlug("train/spec-a"), limit=5)).fetchall()

            # Should have 1 critique
            assert len(result) == 1

            # Check structure
            row = result[0]
            assert row.id is not None
            assert row.payload is not None
            assert row.created_at is not None
            assert row.prompt_sha256 == "a" * 64
            assert row.model == "test-model"

    def test_tools_used_by_transcript(self, query_test_data):
        """tools_used_by_transcript() returns tool usage counts for a transcript."""
        transcript_id = query_test_data
        with get_session() as session:
            result = session.execute(qb.tools_used_by_transcript(transcript_id)).fetchall()

            # Should have 2 different tools (Read, Grep)
            assert len(result) >= 2

            # Check structure
            tools = {row.tool_name: row.count for row in result}
            assert "Read" in tools
            assert "Grep" in tools

    def test_tool_sequence_by_transcript(self, query_test_data):
        """tool_sequence_by_transcript() returns tool calls in chronological order."""
        transcript_id = query_test_data
        with get_session() as session:
            result = session.execute(qb.tool_sequence_by_transcript(transcript_id)).fetchall()

            # Should have 2 tool calls
            assert len(result) >= 2

            # Check ordering by sequence_num
            assert result[0].sequence_num == 0
            assert result[0].tool_name == "Read"
            assert result[1].sequence_num == 2
            assert result[1].tool_name == "Grep"

    def test_failed_tools_by_transcript(self, query_test_data):
        """failed_tools_by_transcript() returns tools with isError=true in results."""
        transcript_id = query_test_data
        with get_session() as session:
            result = session.execute(qb.failed_tools_by_transcript(transcript_id)).fetchall()

            # Should have 1 failed tool (Grep)
            assert len(result) >= 1

            # Check first failure
            row = result[0]
            assert row.tool_name == "Grep"
            assert row.is_error == "true"  # JSONB returns string


class TestJsonbNullFiltering:
    """Test that queries properly filter out JSONB null values.

    JSONB null is different from SQL NULL:
    - SQL NULL: column value is not present (output IS NULL) - NOT possible in schema
    - JSONB null: column contains the JSON literal `null` (output = 'null'::jsonb)

    The database schema has output NOT NULL, so only JSONB null values are possible.
    Queries must filter out JSONB null values to avoid null metrics in results.

    Note: We use raw SQL to insert test data to precisely control JSONB content.
    """

    def test_recent_grader_results_excludes_jsonb_null_output(self, test_db, test_prompt_sha):
        """Grader runs with JSONB null output are excluded from recent_grader_results.

        This tests the case where output column IS NOT NULL but contains JSON `null`.
        """
        critique_id = uuid4()
        grader_with_jsonb_null_id = uuid4()

        with get_session() as session:
            # Setup: snapshot and critique
            session.merge(Snapshot(slug="train/jsonb-null-test", split="train"))
            session.flush()

            session.add(
                Critique(id=critique_id, snapshot_slug="train/jsonb-null-test", payload={"issues": [], "notes_md": ""})
            )
            session.commit()

            # Insert grader run with JSONB null output using raw SQL
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/jsonb-null-test', 'test-jsonb-null-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        'null'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_with_jsonb_null_id), "cid": str(critique_id)},
            )
            session.commit()

            # Verify the JSONB null was set correctly
            check = session.execute(
                text(
                    """
                    SELECT
                        output IS NULL as is_sql_null,
                        output = 'null'::jsonb as is_jsonb_null,
                        output->'grade' IS NULL as grade_is_null
                    FROM grader_runs
                    WHERE transcript_id = :tid
                    """
                ),
                {"tid": str(grader_with_jsonb_null_id)},
            ).fetchone()
            assert check is not None, "Expected row not found"
            assert check.is_sql_null is False, "Column should NOT be SQL NULL"
            assert check.is_jsonb_null is True, "Column should contain JSONB null"
            assert check.grade_is_null is True, "grade field should be null"

        with get_session() as session:
            result = session.execute(qb.recent_grader_results(limit=100)).fetchall()
            jsonb_null_runs = [r for r in result if r.snapshot_slug == "train/jsonb-null-test"]
            assert len(jsonb_null_runs) == 0, "Grader runs with JSONB null output should be excluded"

    def test_recent_grader_results_excludes_missing_grade_field(self, test_db, test_prompt_sha):
        """Grader runs with output missing 'grade' field are excluded from recent_grader_results."""
        critique_id = uuid4()
        grader_missing_grade_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/missing-grade-test", split="train"))
            session.flush()

            session.add(
                Critique(
                    id=critique_id, snapshot_slug="train/missing-grade-test", payload={"issues": [], "notes_md": ""}
                )
            )
            session.commit()

            # Insert grader run with output that has NO 'grade' field
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/missing-grade-test', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        '{"error": "grading failed", "partial": true}'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_missing_grade_id), "cid": str(critique_id)},
            )
            session.commit()

        with get_session() as session:
            result = session.execute(qb.recent_grader_results(limit=100)).fetchall()
            missing_grade_runs = [r for r in result if r.snapshot_slug == "train/missing-grade-test"]
            assert len(missing_grade_runs) == 0, "Grader runs with missing grade field should be excluded"

    def test_recent_grader_results_includes_valid_output(self, test_db, test_prompt_sha):
        """Grader runs with proper output containing grade field are included."""
        critique_id = uuid4()
        grader_valid_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/valid-output-test", split="train"))
            session.flush()

            session.add(
                Critique(
                    id=critique_id, snapshot_slug="train/valid-output-test", payload={"issues": [], "notes_md": ""}
                )
            )
            session.commit()

            # Build valid output JSON matching GraderOutput Pydantic schema
            valid_output = make_grader_output(
                tp_count=2, fp_count=1, recall=0.5, tp_ratio=0.6, fp_ratio=0.2, summary="Valid output test"
            )
            valid_output_json = json.dumps(valid_output)

            # Insert grader run with valid output using raw SQL
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/valid-output-test', 'test-valid-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        CAST(:output AS jsonb)
                    )
                    """
                ),
                {"tid": str(grader_valid_id), "cid": str(critique_id), "output": valid_output_json},
            )
            session.commit()

        with get_session() as session:
            result = session.execute(qb.recent_grader_results(limit=100)).fetchall()
            valid_runs = [r for r in result if r.snapshot_slug == "train/valid-output-test"]
            assert len(valid_runs) == 1, "Grader runs with valid output should be included"
            assert valid_runs[0].recall == "0.5"
            # Verify new schema fields work
            assert valid_runs[0].canonical_tp_count == 2
            assert valid_runs[0].canonical_fp_count == 1
            assert valid_runs[0].reported_tp_ratio == "0.6"

    def test_grader_runs_by_scope_excludes_jsonb_null(self, test_db, test_prompt_sha):
        """grader_runs_by_scope_train() excludes grader runs with JSONB null output."""
        critique_id = uuid4()
        grader_id = uuid4()

        with get_session() as session:
            session.merge(Snapshot(slug="train/scope-null-test", split="train"))
            session.flush()

            session.add(
                Critique(id=critique_id, snapshot_slug="train/scope-null-test", payload={"issues": [], "notes_md": ""})
            )
            session.flush()

            # Create scope and critic run with matching files_hash
            session.add(
                CriticScopeDB(snapshot_slug="train/scope-null-test", files=TEST_FILES_LIST, files_hash=TEST_FILES_HASH)
            )
            session.flush()

            session.add(
                CriticRun(
                    transcript_id=uuid4(),
                    prompt_sha256=test_prompt_sha,
                    snapshot_slug="train/scope-null-test",
                    model="test-model",
                    critique_id=critique_id,
                    files=TEST_FILES_LIST,
                    files_hash=TEST_FILES_HASH,
                    output={"tag": "success"},
                )
            )
            session.commit()

            # Insert grader run with JSONB null output using raw SQL
            session.execute(
                text(
                    """
                    INSERT INTO grader_runs (
                        id, transcript_id, snapshot_slug, model, critique_id,
                        canonical_issues_snapshot, output
                    ) VALUES (
                        gen_random_uuid(), :tid, 'train/scope-null-test', 'test-model', :cid,
                        '{"true_positives": [], "false_positives": []}'::jsonb,
                        'null'::jsonb
                    )
                    """
                ),
                {"tid": str(grader_id), "cid": str(critique_id)},
            )
            session.commit()

        with get_session() as session:
            result = session.execute(qb.grader_runs_by_scope_train(limit=100)).fetchall()
            scope_null_runs = [r for r in result if r.snapshot_slug == "train/scope-null-test"]
            assert len(scope_null_runs) == 0, "grader_runs_by_scope_train should exclude JSONB null output"
