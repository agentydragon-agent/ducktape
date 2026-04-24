"""EventStore tests — append, load, ETag, event log pagination."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel

from x.auragon_study_casino.store import EventStore, IncomingEvent, StaleETagError


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "state.db")


def _ev(type: str, **payload: object) -> IncomingEvent:
    return IncomingEvent(type=type, ts_ms=1_700_000_000_000, payload=dict(payload))


def test_load_on_empty_db_returns_initial_state(store: EventStore) -> None:
    loaded = store.load()
    assert loaded.state["credits"] == 0
    assert loaded.last_event_id == 0
    assert loaded.etag  # non-empty


def test_append_single_event_updates_snapshot(store: EventStore) -> None:
    before = store.load()
    after = store.append([_ev("credits_delta", amount=50)])
    assert after.state["credits"] == 50
    assert after.last_event_id == 1
    assert after.etag != before.etag


def test_append_empty_list_rejected(store: EventStore) -> None:
    with pytest.raises(ValueError, match="no events"):
        store.append([])


def test_append_batch_yields_contiguous_ids(store: EventStore) -> None:
    after = store.append(
        [_ev("credits_delta", amount=10), _ev("credits_delta", amount=20), _ev("tokens_delta", amount=5)]
    )
    assert after.state["credits"] == 30
    assert after.state["tokens"] == 5
    assert after.last_event_id == 3


def test_append_with_matching_if_match_succeeds(store: EventStore) -> None:
    first = store.append([_ev("credits_delta", amount=10)])
    second = store.append([_ev("credits_delta", amount=5)], if_match=first.etag)
    assert second.state["credits"] == 15


def test_append_with_stale_if_match_raises_stale_etag(store: EventStore) -> None:
    store.append([_ev("credits_delta", amount=10)])
    with pytest.raises(StaleETagError):
        store.append([_ev("credits_delta", amount=5)], if_match='"stale"')


def test_malformed_event_rolls_back_entire_batch(store: EventStore) -> None:
    # Mix a good event with a bad one; nothing should be persisted.
    before = store.load()
    with pytest.raises(ValueError, match="unknown event type"):
        store.append([_ev("credits_delta", amount=10), _ev("bogus_type")])
    after = store.load()
    assert after.state == before.state
    assert after.last_event_id == before.last_event_id


def test_list_events_returns_log_in_order(store: EventStore) -> None:
    store.append([_ev("credits_delta", amount=10), _ev("tokens_delta", amount=3), _ev("credits_delta", amount=-5)])
    events = store.list_events()
    assert [e["type"] for e in events] == ["credits_delta", "tokens_delta", "credits_delta"]
    assert [e["payload"]["amount"] for e in events] == [10, 3, -5]


def test_list_events_since_id_filter(store: EventStore) -> None:
    store.append([_ev("credits_delta", amount=1), _ev("credits_delta", amount=2)])
    events = store.list_events(since_id=1)
    assert len(events) == 1
    assert events[0]["payload"]["amount"] == 2


def test_list_events_limit(store: EventStore) -> None:
    store.append([_ev("credits_delta", amount=i) for i in range(5)])
    events = store.list_events(limit=2)
    assert len(events) == 2


def test_snapshot_persists_across_store_instances(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    EventStore(db).append([_ev("credits_delta", amount=100), _ev("tokens_delta", amount=50)])
    reopened = EventStore(db)
    loaded = reopened.load()
    assert loaded.state["credits"] == 100
    assert loaded.state["tokens"] == 50
    assert loaded.last_event_id == 2


if __name__ == "__main__":
    pytest_bazel.main()
