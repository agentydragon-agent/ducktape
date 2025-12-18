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
from uuid import uuid4

import pytest

from adgn.props.db import get_session, query_builders as qb
from adgn.props.db.examples import Example
from adgn.props.db.models import (
    AggregatedRecallByPrompt,
    CriticRun,
    CriticRunStatus,
    Event,
    FalsePositive,
    Snapshot,
    TruePositive,
)
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.splits import Split
from tests.props.conftest import make_grader_run

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


@pytest.fixture
def query_test_data(synced_test_fixtures):
    """Populate database with critic/grader runs for query validation.

    Uses git fixtures for ground truth (Snapshots, TPs, FPs, Examples).
    Creates:
    - 1 prompt
    - 3 critic runs (1 train, 2 valid)
    - 3 grader runs (1 train, 2 valid)
    - Event records (tool_call and function_call_output events)

    Note: Git fixtures provide:
    - test-trivial (TRAIN) - has TPs and examples
    - test-validation (VALID) - has TPs and examples
    - test-validation-2 (VALID) - has TPs and examples
    """
    with get_session() as session:
        # Query git fixture examples (snapshots/TPs/FPs already loaded by synced_test_fixtures)
        # Use explicit join and select columns to avoid lazy loading issues
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == Split.TRAIN)
            .limit(2)
            .all()
        )
        valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == Split.VALID)
            .limit(2)
            .all()
        )

        assert len(train_examples) >= 1, "Need at least 1 train example from git fixtures"
        assert len(valid_examples) >= 2, "Need at least 2 valid examples from git fixtures"

        # Extract values while session is open (avoid DetachedInstanceError)
        train_0_slug = train_examples[0].snapshot_slug
        train_0_hash = train_examples[0].scope_hash
        valid_0_slug = valid_examples[0].snapshot_slug
        valid_0_hash = valid_examples[0].scope_hash
        valid_1_slug = valid_examples[1].snapshot_slug
        valid_1_hash = valid_examples[1].scope_hash

        # Create prompt (helper computes proper hash)
        prompt_sha = hash_and_upsert_prompt("Test prompt for query validation")

        # Create critic runs directly with extracted values (avoid passing detached Example objects)
        critic_run_train = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=prompt_sha,
            snapshot_slug=train_0_slug,
            scope_hash=train_0_hash,
            model="test-model",
            status=CriticRunStatus.COMPLETED,
            completion_summary="Test completion summary for train",
        )
        session.add(critic_run_train)

        critic_run_valid_1 = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=prompt_sha,
            snapshot_slug=valid_0_slug,
            scope_hash=valid_0_hash,
            model="test-model",
            status=CriticRunStatus.COMPLETED,
            completion_summary="Test completion summary for valid-1",
        )
        session.add(critic_run_valid_1)

        critic_run_valid_2 = CriticRun(
            transcript_id=uuid4(),
            prompt_sha256=prompt_sha,
            snapshot_slug=valid_1_slug,
            scope_hash=valid_1_hash,
            model="test-model",
            status=CriticRunStatus.COMPLETED,
            completion_summary="Test completion summary for valid-2",
        )
        session.add(critic_run_valid_2)

        session.flush()

        # Create grader runs using factory
        grader_run_train = make_grader_run(critic_run=critic_run_train)
        session.add(grader_run_train)

        grader_run_valid_1 = make_grader_run(critic_run=critic_run_valid_1)
        session.add(grader_run_valid_1)

        grader_run_valid_2 = make_grader_run(critic_run=critic_run_valid_2)
        session.add(grader_run_valid_2)

        session.flush()

        # Create event records for one transcript_id (for event query tests)
        test_transcript_id = critic_run_train.transcript_id
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

            # Should have at least 1 train snapshot from git fixtures
            assert len(result) >= 1

            # Check first row has expected columns and values
            assert "test-fixtures/" in result[0].slug  # Git fixtures use test-fixtures/ prefix
            assert result[0].split == "train"

            # Check ordering (slugs should be sorted)
            slugs = [row.slug for row in result]
            assert slugs == sorted(slugs)

    def test_list_train_true_positives(self, query_test_data):
        """list_train_true_positives() returns all TPs for train split."""
        with get_session() as session:
            result = session.execute(qb.list_train_true_positives()).fetchall()

            # Should have at least 1 train true positive from git fixtures
            assert len(result) >= 1

            # Check structure
            assert "test-fixtures/" in result[0].snapshot_slug
            assert result[0].tp_id is not None
            assert result[0].rationale is not None

    def test_list_train_false_positives(self, query_test_data):
        """list_train_false_positives() returns all FPs for train split."""
        with get_session() as session:
            result = session.execute(qb.list_train_false_positives()).fetchall()

            # Git fixtures may or may not have FPs - just check structure if any exist
            if len(result) > 0:
                # Check structure
                assert "test-fixtures/" in result[0].snapshot_slug
                assert result[0].fp_id is not None
                assert result[0].rationale is not None

    def test_count_issues_by_snapshot(self, query_test_data):
        """count_issues_by_snapshot() returns TP/FP counts per snapshot."""
        with get_session() as session:
            result = session.execute(qb.count_issues_by_snapshot(split=Split.TRAIN)).fetchall()

            # Should have at least 1 train snapshot from git fixtures
            assert len(result) >= 1

            # Check structure - all should be from test-fixtures
            for row in result:
                assert "test-fixtures/" in row.snapshot_slug
                assert row.tp_count >= 0
                assert row.fp_count >= 0
                # tp_count and fp_count should be integers
                assert isinstance(row.tp_count, int)
                assert isinstance(row.fp_count, int)

    def test_list_true_positives_for_snapshot(self, query_test_data):
        """list_true_positives_for_snapshot() returns TPs for specific snapshot."""
        with get_session() as session:
            # Find a TRAIN snapshot with TPs
            train_snapshot = (
                session.query(Snapshot)
                .filter(Snapshot.split == Split.TRAIN)
                .join(TruePositive, TruePositive.snapshot_slug == Snapshot.slug)
                .first()
            )
            assert train_snapshot, "No TRAIN snapshot with TPs found"

            result = session.execute(qb.list_true_positives_for_snapshot(train_snapshot.slug)).fetchall()

            # Should have at least 1 TP
            assert len(result) >= 1
            assert result[0].tp_id is not None
            assert result[0].rationale is not None
            assert len(result[0].occurrences) >= 1

    def test_list_false_positives_for_snapshot(self, query_test_data):
        """list_false_positives_for_snapshot() returns FPs for specific snapshot."""
        with get_session() as session:
            # Find a TRAIN snapshot with FPs (if any exist)
            train_snapshot_with_fps = (
                session.query(Snapshot)
                .filter(Snapshot.split == Split.TRAIN)
                .join(FalsePositive, FalsePositive.snapshot_slug == Snapshot.slug)
                .first()
            )

            if train_snapshot_with_fps:
                result = session.execute(qb.list_false_positives_for_snapshot(train_snapshot_with_fps.slug)).fetchall()
                # Should have at least 1 FP
                assert len(result) >= 1
                assert result[0].fp_id is not None
                assert result[0].rationale is not None
                assert len(result[0].occurrences) >= 1
            else:
                # If no FPs, just verify empty result for any TRAIN snapshot
                train_snapshot = session.query(Snapshot).filter(Snapshot.split == Split.TRAIN).first()
                assert train_snapshot, "No TRAIN snapshot found"
                result = session.execute(qb.list_false_positives_for_snapshot(train_snapshot.slug)).fetchall()
                assert len(result) == 0

    def test_valid_aggregates_view(self, query_test_data):
        """aggregated_recall_by_prompt view computes statistics for valid split."""

        with get_session() as session:
            # Query the aggregated_recall_by_prompt view for valid split
            result = session.query(AggregatedRecallByPrompt).filter(AggregatedRecallByPrompt.split == Split.VALID).all()

            # Should have at least 1 row (from valid grader runs created in fixture)
            assert len(result) >= 1

            # Check first row has expected structure (occurrence-based metrics)
            row = result[0]
            # Check occurrence counts are non-negative
            assert row.avg_occurrences_caught_overall >= 0.0
            assert row.avg_catchable_occurrences >= 0.0
            assert row.total_catchable_occurrences >= 0
            # Check count fields
            assert row.n_successful >= 0
            assert row.n_max_turns_exceeded >= 0
            assert row.n_context_length_exceeded >= 0

    def test_critic_runs_for_snapshot(self, query_test_data):
        """critic_runs_for_snapshot() returns critic runs for a specific snapshot."""
        with get_session() as session:
            # Find a TRAIN snapshot that has critic runs
            train_example = (
                session.query(Example)
                .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
                .filter(Snapshot.split == Split.TRAIN)
                .first()
            )
            assert train_example, "No TRAIN example found"

            result = session.execute(qb.critic_runs_for_snapshot(train_example.snapshot_slug, limit=5)).fetchall()

            # Should have at least 1 critic run (created in query_test_data fixture)
            assert len(result) >= 1

            # Check structure
            row = result[0]
            assert row.id is not None
            assert row.status is not None  # CriticRunStatus enum value
            assert row.created_at is not None
            assert len(row.prompt_sha256) == 64  # SHA256 hash
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
