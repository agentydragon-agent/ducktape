"""Tests for GEPA warm-start functionality."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Critique, GraderRun, Prompt, Snapshot
from adgn.props.files_hash import hash_critic_scope_files
from adgn.props.gepa.models import SnapshotInput
from adgn.props.gepa.warm_start import build_historical_gepa_state
from adgn.props.grader.models import (
    GraderOutput,
    GradeSubmitInput,
    NovelIssueEntry,
    NovelIssueReasoning,
    ReportedIssueRatios,
)
from adgn.props.ids import InputIssueID, SnapshotSlug
from adgn.props.splits import Split


def make_grader_output(recall: float) -> GraderOutput:
    """Helper to create GraderOutput for tests."""
    return GraderOutput(
        grade=GradeSubmitInput(
            canonical_tp_coverage=[],
            canonical_fp_coverage=[],
            novel_critique_issues=[
                NovelIssueEntry(
                    input_id=InputIssueID("test-issue"),
                    reasoning=NovelIssueReasoning(rationale="Test rationale for grader"),
                )
            ],
            reported_issue_ratios=ReportedIssueRatios(tp=0.0, fp=0.0, unlabeled=1.0),
            recall=recall,
            summary="Test grader output",
        )
    )


@pytest.fixture
def standard_valset() -> list[SnapshotInput]:
    """Standard two-snapshot validation set for most tests."""
    return [
        SnapshotInput(slug=SnapshotSlug("test/valid-1"), target_files={Path("hash1")}),
        SnapshotInput(slug=SnapshotSlug("test/valid-2"), target_files={Path("hash2")}),
    ]


@pytest.fixture
def db_with_historical_runs(test_db):
    """Fixture providing database with historical critic + grader runs."""
    # test_db fixture already initializes and recreates the database

    # Compute proper file hashes for test data
    hash1 = hash_critic_scope_files({Path("hash1")})
    hash2 = hash_critic_scope_files({Path("hash2")})
    hash3 = hash_critic_scope_files({Path("hash3")})
    hash_train = hash_critic_scope_files({Path("hash_train")})

    with get_session() as session:
        # Create snapshots
        snap_valid_1 = Snapshot(slug=SnapshotSlug("test/valid-1"), split=Split.VALID)
        snap_valid_2 = Snapshot(slug=SnapshotSlug("test/valid-2"), split=Split.VALID)
        snap_train = Snapshot(slug=SnapshotSlug("test/train-1"), split=Split.TRAIN)
        session.add_all([snap_valid_1, snap_valid_2, snap_train])

        # Create prompts
        prompt_a = Prompt(
            prompt_sha256="aaaa" * 16,  # 64 hex chars
            prompt_text="You are a code critic (version A).",
        )
        prompt_b = Prompt(prompt_sha256="bbbb" * 16, prompt_text="You are a code critic (version B).")
        session.add_all([prompt_a, prompt_b])

        # Create critiques (with snapshot_slug required)
        empty_payload = CriticSubmitPayload(issues=[], notes_md=None)
        critique_1 = Critique(id=uuid4(), snapshot_slug=snap_valid_1.slug, payload=empty_payload)
        critique_2 = Critique(id=uuid4(), snapshot_slug=snap_valid_2.slug, payload=empty_payload)
        critique_3 = Critique(id=uuid4(), snapshot_slug=snap_valid_1.slug, payload=empty_payload)
        critique_incomplete = Critique(id=uuid4(), snapshot_slug=snap_valid_1.slug, payload=empty_payload)
        critique_train = Critique(id=uuid4(), snapshot_slug=snap_train.slug, payload=empty_payload)
        session.add_all([critique_1, critique_2, critique_3, critique_incomplete, critique_train])

        session.commit()

        # Create critic runs
        critic_run_1 = CriticRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_valid_1.slug,
            model="test-model",
            critique_id=critique_1.id,
            prompt_sha256=prompt_a.prompt_sha256,
            files_hash=hash1,
            files=[],
            output={},
        )
        critic_run_2 = CriticRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_valid_2.slug,
            model="test-model",
            critique_id=critique_2.id,
            prompt_sha256=prompt_a.prompt_sha256,
            files_hash=hash2,
            files=[],
            output={},
        )
        critic_run_3 = CriticRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_valid_1.slug,
            model="test-model",
            critique_id=critique_3.id,
            prompt_sha256=prompt_b.prompt_sha256,
            files_hash=hash1,
            files=[],
            output={},
        )
        # Incomplete run (no critique_id)
        critic_run_incomplete = CriticRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_valid_1.slug,
            model="test-model",
            critique_id=None,  # Incomplete
            prompt_sha256=prompt_a.prompt_sha256,
            files_hash=hash3,
            files=[],
            output={},
        )
        # Run on training set (should be excluded)
        critic_run_train = CriticRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_train.slug,
            model="test-model",
            critique_id=critique_train.id,
            prompt_sha256=prompt_a.prompt_sha256,
            files_hash=hash_train,
            files=[],
            output={},
        )
        session.add_all([critic_run_1, critic_run_2, critic_run_3, critic_run_incomplete, critic_run_train])

        session.commit()

        # Create grader runs
        grader_run_1 = GraderRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_valid_1.slug,
            model="test-model",
            critique_id=critique_1.id,
            output=make_grader_output(recall=0.8),
        )
        grader_run_2 = GraderRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_valid_2.slug,
            model="test-model",
            critique_id=critique_2.id,
            output=make_grader_output(recall=0.6),
        )
        grader_run_3 = GraderRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_valid_1.slug,
            model="test-model",
            critique_id=critique_3.id,
            output=make_grader_output(recall=0.9),
        )
        # Grader run with JSON null output (simulates incomplete/failed grader)
        grader_run_null = GraderRun(
            transcript_id=uuid4(),
            snapshot_slug=snap_valid_1.slug,
            model="test-model",
            critique_id=critique_incomplete.id,
            output=None,  # This gets stored as JSON null in JSONB
        )
        session.add_all([grader_run_1, grader_run_2, grader_run_3, grader_run_null])

        session.commit()

    # test_db fixture handles cleanup


def test_build_historical_state_basic(db_with_historical_runs, standard_valset):
    """Test basic warm-start state building from historical runs."""
    state = build_historical_gepa_state(valset=standard_valset, critic_model="test-model", grader_model="test-model")

    assert state is not None
    assert state["validation_schema_version"] == 2

    # Should have 2 unique prompts (prompt_a and prompt_b)
    assert len(state["program_candidates"]) == 2

    # Check sparse validation scores structure
    assert len(state["prog_candidate_val_subscores"]) == 2

    # Prompt A was evaluated on valid-1 (recall=0.8) and valid-2 (recall=0.6)
    # Prompt B was evaluated on valid-1 (recall=0.9)
    prompt_a_scores = None
    prompt_b_scores = None
    for prog_idx, candidate in enumerate(state["program_candidates"]):
        if "version A" in candidate["system_prompt"]:
            prompt_a_scores = state["prog_candidate_val_subscores"][prog_idx]
        elif "version B" in candidate["system_prompt"]:
            prompt_b_scores = state["prog_candidate_val_subscores"][prog_idx]

    assert prompt_a_scores is not None
    assert prompt_b_scores is not None

    # Prompt A: evaluated on both validation examples
    assert len(prompt_a_scores) == 2
    assert 0 in prompt_a_scores  # valid-1 (valset[0])
    assert 1 in prompt_a_scores  # valid-2 (valset[1])
    assert prompt_a_scores[0] == 0.8
    assert prompt_a_scores[1] == 0.6

    # Prompt B: evaluated only on valid-1
    assert len(prompt_b_scores) == 1
    assert 0 in prompt_b_scores
    assert prompt_b_scores[0] == 0.9

    # Check Pareto frontier: valid-1 should have prompt_b (0.9), valid-2 should have prompt_a (0.6)
    assert 0 in state["pareto_front_valset"]
    assert 1 in state["pareto_front_valset"]
    assert state["pareto_front_valset"][0] == 0.9  # Best for valid-1
    assert state["pareto_front_valset"][1] == 0.6  # Best for valid-2

    # Check total_num_evals is 0 (budget applies to current run only)
    assert state["total_num_evals"] == 0


def test_json_null_filtering(db_with_historical_runs, standard_valset):
    """Test that grader runs with JSON null output are properly excluded."""
    state = build_historical_gepa_state(valset=standard_valset, critic_model="test-model", grader_model="test-model")

    # Should succeed without AttributeError on None.recall
    assert state is not None

    # The incomplete run with JSON null output should not appear in any scores
    # We have 3 valid grader outputs, so total scores across all prompts should be 3
    total_scores = sum(len(scores) for scores in state["prog_candidate_val_subscores"])
    assert total_scores == 3


def test_empty_database(test_db):
    """Test warm-start with no historical data returns None."""
    # test_db fixture already initializes and recreates database

    valset = [SnapshotInput(slug=SnapshotSlug("test/valid-1"), target_files={Path("hash1")})]

    state = build_historical_gepa_state(valset=valset, critic_model="test-model", grader_model="test-model")

    assert state is None


def test_model_filtering(db_with_historical_runs):
    """Test that only runs matching specified models are included."""
    # Database already initialized by test_db fixture

    valset = [SnapshotInput(slug=SnapshotSlug("test/valid-1"), target_files={Path("hash1")})]

    # Query with non-matching model
    state = build_historical_gepa_state(valset=valset, critic_model="wrong-model", grader_model="test-model")

    assert state is None  # No matching runs


def test_split_filtering(db_with_historical_runs):
    """Test that only validation split runs are included (not training)."""
    # Database already initialized by test_db fixture

    # Query with training example (should find nothing)
    valset = [SnapshotInput(slug=SnapshotSlug("test/train-1"), target_files={Path("hash_train")})]

    state = build_historical_gepa_state(valset=valset, critic_model="test-model", grader_model="test-model")

    # Training split should be excluded from validation set queries
    assert state is None


def test_unknown_examples_skipped(db_with_historical_runs):
    """Test that examples not in current valset are skipped with warning."""
    # Database already initialized by test_db fixture

    # Valset that doesn't include valid-2 (but database has runs for it)
    valset = [SnapshotInput(slug=SnapshotSlug("test/valid-1"), target_files={Path("hash1")})]

    state = build_historical_gepa_state(valset=valset, critic_model="test-model", grader_model="test-model")

    assert state is not None

    # Should have scores only for valid-1, not valid-2
    total_scores = sum(len(scores) for scores in state["prog_candidate_val_subscores"])
    assert total_scores == 2  # 2 prompts evaluated on valid-1

    # All scores should be keyed by index 0 (valid-1)
    for scores in state["prog_candidate_val_subscores"]:
        assert set(scores) == {0}


def test_files_hash_matching(db_with_historical_runs):
    """Test that (snapshot_slug, files_hash) tuple matching works correctly."""
    # Database already initialized by test_db fixture

    # Valset with same snapshot but different files_hash (should not match)
    valset = [SnapshotInput(slug=SnapshotSlug("test/valid-1"), target_files={Path("hash_different")})]

    state = build_historical_gepa_state(valset=valset, critic_model="test-model", grader_model="test-model")

    # No matches because files_hash doesn't match
    assert state is None


def test_critic_scope_spec_all(db_with_historical_runs):
    """Test that CriticScopeSpec 'all' is handled correctly in index mapping."""
    # Database already initialized by test_db fixture

    # Create valset with "all" scope
    valset = [SnapshotInput(slug=SnapshotSlug("test/valid-1"), target_files="all")]

    # This should not match database runs (which have specific file hashes)
    state = build_historical_gepa_state(valset=valset, critic_model="test-model", grader_model="test-model")

    # No matches because "all" hashes to a different value than "hash1"
    assert state is None


def test_deterministic_ordering(db_with_historical_runs, standard_valset):
    """Test that prompt candidates are returned in deterministic order."""
    # Run multiple times and check order is consistent
    state1 = build_historical_gepa_state(valset=standard_valset, critic_model="test-model", grader_model="test-model")
    state2 = build_historical_gepa_state(valset=standard_valset, critic_model="test-model", grader_model="test-model")

    assert state1 is not None
    assert state2 is not None

    # Prompts should be in same order (sorted by SHA for determinism)
    prompts1 = [c["system_prompt"] for c in state1["program_candidates"]]
    prompts2 = [c["system_prompt"] for c in state2["program_candidates"]]
    assert prompts1 == prompts2

    # Scores should match
    assert state1["prog_candidate_val_subscores"] == state2["prog_candidate_val_subscores"]
