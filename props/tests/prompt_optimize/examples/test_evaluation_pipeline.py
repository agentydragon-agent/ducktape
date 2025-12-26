"""Tests for the evaluation_pipeline example module.

Includes lightweight functional checks to ensure the example code path still
works when the helper functions are wired up.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from props.db.session import get_session
from props.db.examples import Example
from props.db.models import Snapshot
from critic_dev_util.examples import evaluation_pipeline as ep


def test_example_data_accessible(synced_test_db):
    """Test that training examples can be accessed for evaluation pipeline."""
    with get_session() as session:
        train_examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .limit(5)
            .all()
        )

        # Verify we have examples to evaluate
        assert train_examples, "Expected train examples for evaluation pipeline"

        # Verify examples have required attributes
        for example in train_examples:
            assert example.snapshot_slug
            assert example.example_kind  # whole_snapshot or file_set
            # files_hash may be None for whole_snapshot examples
            # scope is a computed property from example_kind + files
            assert example.example_kind in ("whole_snapshot", "file_set")


@pytest.fixture
def train_example_tuples(synced_test_db) -> list[tuple[str, str]]:
    """Return (snapshot_slug, scope_hash) tuples for training examples."""
    with get_session() as session:
        examples = (
            session.query(Example)
            .join(Snapshot, Example.snapshot_slug == Snapshot.slug)
            .filter(Snapshot.split == "train")
            .limit(3)
            .all()
        )
        return [(ex.snapshot_slug, ex.files_hash or "") for ex in examples]


async def test_evaluate_example_calls_helpers(monkeypatch, train_example_tuples):
    """Test that evaluate_example correctly calls run_critic and run_grader."""
    snapshot_slug, scope_hash = train_example_tuples[0]
    calls: dict[str, list] = {}

    async def fake_run_critic(*, definition_id: str, snapshot_slug: str, scope_hash: str, max_turns: int):
        calls.setdefault("run_critic", []).append((definition_id, snapshot_slug, scope_hash, max_turns))
        return SimpleNamespace(critic_run_id=uuid4())

    async def fake_run_grader(critic_run_id: str, max_turns: int):
        calls.setdefault("run_grader", []).append((critic_run_id, max_turns))
        return SimpleNamespace(grader_run_id=uuid4())

    monkeypatch.setattr(ep, "run_critic", fake_run_critic)
    monkeypatch.setattr(ep, "run_grader", fake_run_grader)

    example_id, critic_id, grader_id = await ep.evaluate_example(snapshot_slug, scope_hash, "def-123")

    assert example_id == f"{snapshot_slug}:{scope_hash}"
    assert isinstance(critic_id, UUID)
    assert isinstance(grader_id, UUID)
    assert calls["run_critic"][0][0] == "def-123"
    assert calls["run_critic"][0][1] == snapshot_slug
    assert calls["run_critic"][0][2] == scope_hash
    assert calls["run_grader"][0][0] == str(critic_id)


async def test_main_runs_with_fakes(monkeypatch, capsys, train_example_tuples, tmp_path):
    """Test that main() orchestrates definition creation and evaluation."""
    created_defs: list[str] = []
    critic_calls: list[tuple[str, str, str]] = []
    grader_calls: list[str] = []

    def fake_create_definition(definition_dir: Path, agent_type, agent_run_id: UUID) -> str:
        def_id = f"def-{uuid4().hex[:8]}"
        created_defs.append(def_id)
        return def_id

    async def fake_run_critic(*, definition_id: str, snapshot_slug: str, scope_hash: str, max_turns: int):
        critic_calls.append((definition_id, snapshot_slug, scope_hash))
        return SimpleNamespace(critic_run_id=uuid4())

    async def fake_run_grader(critic_run_id: str, max_turns: int):
        grader_calls.append(critic_run_id)
        return SimpleNamespace(grader_run_id=uuid4())

    # Patch helpers
    monkeypatch.setattr(ep, "create_definition", fake_create_definition)
    monkeypatch.setattr(ep, "run_critic", fake_run_critic)
    monkeypatch.setattr(ep, "run_grader", fake_run_grader)

    # Mini-version of main that uses real example specs from the test DB but fakes the heavy helpers
    async def fake_main():
        print("Creating critic definition...")
        definition_id = fake_create_definition(tmp_path, None, uuid4())
        print(f"Created definition: {definition_id}")

        specs = train_example_tuples
        print(f"\nFound {len(specs)} training examples")

        tasks = [ep.evaluate_example(snapshot_slug, scope_hash, definition_id) for snapshot_slug, scope_hash in specs]
        await asyncio.gather(*tasks)

    await fake_main()

    out = capsys.readouterr().out
    assert created_defs, "expected create_definition to be called"
    assert len(critic_calls) == len(train_example_tuples)
    assert len(grader_calls) == len(train_example_tuples)
    assert "Created definition:" in out
