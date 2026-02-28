"""Integration tests for critic-dev recipe modules.

Uses synced_db (real PostgreSQL + git-tracked test specimens) for all tests.
Exercises the recipe functions against real data to verify they work end-to-end.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_bazel

from props.agents.critic_dev.recipes import examples_and_scopes, ground_truth, recall_metrics, run_analysis
from props.core.ids import SnapshotSlug
from props.core.models.examples import SingleFileSetExample, WholeSnapshotExample
from props.core.splits import Split
from props.db.database import Database
from props.db.examples import Example
from props.db.models import Snapshot
from props.testing.fixtures.runs import make_fake_critic_run, make_fake_grader_run

pytestmark = [pytest.mark.integration]


@pytest.fixture
def recipe_test_data(synced_db: Database):
    """Populate DB with critic/grader runs so recall views have data.

    Builds on synced_db which already provides snapshots, TPs, FPs, and examples
    from git-tracked test fixtures.
    """
    with synced_db.session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == Split.TRAIN)
            .limit(1)
            .all()
        )
        valid_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == Split.VALID)
            .limit(2)
            .all()
        )

        assert len(train_examples) >= 1
        assert len(valid_examples) >= 1

        # Create critic + grader runs for each example
        for example in train_examples + valid_examples:
            critic_run = make_fake_critic_run(session=session, example=example.to_example_spec())
            session.add(critic_run)

            grader_run = make_fake_grader_run(session=session, snapshot_slug=example.snapshot_slug)
            session.add(grader_run)

        session.flush()
        session.commit()


class TestGroundTruth:
    def test_list_snapshots_by_split(self, synced_db: Database, db: Database):
        with db.session() as session:
            train_snapshots = ground_truth.list_snapshots_by_split(session, Split.TRAIN)
            assert len(train_snapshots) >= 1
            for s in train_snapshots:
                assert s.split == Split.TRAIN

    def test_get_true_positives(self, synced_db: Database, db: Database):
        with db.session() as session:
            slug = SnapshotSlug("test-fixtures/train1")
            tps = ground_truth.get_true_positives(session, slug)
            assert len(tps) >= 1
            for tp in tps:
                assert tp.snapshot_slug == slug

    def test_get_false_positives(self, synced_db: Database, db: Database):
        with db.session() as session:
            slug = SnapshotSlug("test-fixtures/train1")
            fps = ground_truth.get_false_positives(session, slug)
            # train1 may or may not have FPs; just check structure
            for fp in fps:
                assert fp.snapshot_slug == slug

    def test_summarize_ground_truth(self, synced_db: Database, db: Database):
        with db.session() as session:
            slug = SnapshotSlug("test-fixtures/train1")
            summary = ground_truth.summarize_ground_truth(session, slug)
            assert "Ground truth for test-fixtures/train1" in summary
            assert "true positive(s)" in summary


class TestRecallMetrics:
    def test_get_definition_leaderboard(self, recipe_test_data, db: Database):
        with db.session() as session:
            leaderboard = recall_metrics.get_definition_leaderboard(session, Split.VALID)
            # May have rows from the grader runs we created
            for row in leaderboard:
                assert row.split == Split.VALID

    def test_compare_definitions_missing(self, recipe_test_data, db: Database):
        with db.session() as session:
            result = recall_metrics.compare_definitions(session, "sha256:aaa", "sha256:bbb", Split.VALID)
            assert "no data" in result

    def test_get_per_example_recall(self, recipe_test_data, db: Database):
        with db.session() as session:
            # Get recall rows (may be empty if grading edges aren't created in fixture)
            rows = recall_metrics.get_per_example_recall(session, "sha256:" + "0" * 64, Split.TRAIN)
            for row in rows:
                assert row.recall >= 0.0


class TestRunAnalysis:
    def test_get_recent_critic_runs(self, recipe_test_data, db: Database):
        with db.session() as session:
            slug = SnapshotSlug("test-fixtures/train1")
            runs = run_analysis.get_recent_critic_runs(session, slug)
            for run in runs:
                assert run.critic_config().example.snapshot_slug == slug

    def test_get_critic_dev_child_runs_empty(self, synced_db: Database, db: Database):
        with db.session() as session:
            # No children for a random UUID
            children = run_analysis.get_critic_dev_child_runs(session, uuid4())
            assert children == []


class TestExamplesAndScopes:
    def test_list_train_examples(self, synced_db: Database, db: Database):
        with db.session() as session:
            examples = examples_and_scopes.list_train_examples(session)
            assert len(examples) >= 1

    def test_get_example_details(self, synced_db: Database, db: Database):
        slug = SnapshotSlug("test-fixtures/train1")
        spec = WholeSnapshotExample(snapshot_slug=slug)
        with db.session() as session:
            example = examples_and_scopes.get_example_details(session, spec)
            assert example.snapshot_slug == slug

    def test_build_example_spec_whole_snapshot(self):
        spec = examples_and_scopes.build_example_spec("test-fixtures/train1")
        assert isinstance(spec, WholeSnapshotExample)
        assert spec.snapshot_slug == "test-fixtures/train1"

    def test_build_example_spec_file_set(self):
        spec = examples_and_scopes.build_example_spec("test-fixtures/train1", files_hash="abc123")
        assert isinstance(spec, SingleFileSetExample)
        assert spec.files_hash == "abc123"


if __name__ == "__main__":
    pytest_bazel.main()
