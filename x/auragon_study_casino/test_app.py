"""Backend integration tests — HTTP surface of the event-sourced API."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel
from fastapi.testclient import TestClient

from x.auragon_study_casino.app import create_app
from x.auragon_study_casino.config import Settings


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(data_dir=tmp_path, frontend_dist_dir=tmp_path / "nonexistent_dist")
    return TestClient(create_app(settings))


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_get_state_empty_returns_initial(client: TestClient) -> None:
    r = client.get("/state")
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["credits"] == 0
    assert body["last_event_id"] == 0
    assert body["etag"] == r.headers["etag"]


def test_post_events_appends_and_returns_new_state(client: TestClient) -> None:
    r = client.post(
        "/events",
        json=[
            {"type": "credits_delta", "ts_ms": 1, "payload": {"amount": 50}},
            {"type": "tokens_delta", "ts_ms": 2, "payload": {"amount": 10}},
        ],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["credits"] == 50
    assert body["state"]["tokens"] == 10
    assert body["last_event_id"] == 2


def test_post_events_empty_list_400s(client: TestClient) -> None:
    r = client.post("/events", json=[])
    assert r.status_code == 400


def test_post_events_malformed_event_400s(client: TestClient) -> None:
    r = client.post("/events", json=[{"type": "bogus", "ts_ms": 0, "payload": {}}])
    assert r.status_code == 400
    assert "unknown event type" in r.json()["detail"]


def test_if_match_rejects_stale_etag(client: TestClient) -> None:
    client.post("/events", json=[{"type": "credits_delta", "ts_ms": 0, "payload": {"amount": 1}}])
    r = client.post(
        "/events",
        headers={"If-Match": '"stale"'},
        json=[{"type": "credits_delta", "ts_ms": 1, "payload": {"amount": 1}}],
    )
    assert r.status_code == 412


def test_if_match_with_current_etag_passes(client: TestClient) -> None:
    first = client.post("/events", json=[{"type": "credits_delta", "ts_ms": 0, "payload": {"amount": 1}}])
    r = client.post(
        "/events",
        headers={"If-Match": first.headers["etag"]},
        json=[{"type": "credits_delta", "ts_ms": 1, "payload": {"amount": 1}}],
    )
    assert r.status_code == 200
    assert r.json()["state"]["credits"] == 2


def test_get_events_returns_raw_log(client: TestClient) -> None:
    client.post(
        "/events",
        json=[
            {"type": "credits_delta", "ts_ms": 1, "payload": {"amount": 10}},
            {"type": "tokens_delta", "ts_ms": 2, "payload": {"amount": 3}},
        ],
    )
    r = client.get("/events")
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 2
    assert events[0]["type"] == "credits_delta"
    assert events[1]["type"] == "tokens_delta"


def test_get_events_pagination(client: TestClient) -> None:
    client.post("/events", json=[{"type": "credits_delta", "ts_ms": i, "payload": {"amount": 1}} for i in range(5)])
    r = client.get("/events?since_id=2&limit=2")
    events = r.json()["events"]
    assert [e["id"] for e in events] == [3, 4]


def test_prize_redemption_end_to_end(client: TestClient) -> None:
    # Seed tokens, redeem a prize, check state.
    client.post("/events", json=[{"type": "tokens_delta", "ts_ms": 0, "payload": {"amount": 100}}])
    r = client.post(
        "/events",
        json=[
            {"type": "prize_redeemed", "ts_ms": 1, "payload": {"id": "log1", "name": "Coffee", "cost": 60, "at_ms": 1}}
        ],
    )
    assert r.status_code == 200
    state = r.json()["state"]
    assert state["tokens"] == 40
    assert len(state["prizeLog"]) == 1


def test_prize_redemption_insufficient_tokens_400s(client: TestClient) -> None:
    r = client.post(
        "/events",
        json=[{"type": "prize_redeemed", "ts_ms": 0, "payload": {"id": "x", "name": "y", "cost": 1, "at_ms": 0}}],
    )
    assert r.status_code == 400
    assert "insufficient tokens" in r.json()["detail"]


if __name__ == "__main__":
    pytest_bazel.main()
