"""HTTP-surface tests for the /sync endpoint."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

import pytest
import pytest_bazel
from fastapi.testclient import TestClient
from pycrdt import Map

from x.auragon_study_casino.app import create_app
from x.auragon_study_casino.config import Settings
from x.auragon_study_casino.doc_shape import Casino


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(data_dir=tmp_path, frontend_dist_dir=tmp_path / "nonexistent_dist")
    return TestClient(create_app(settings))


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


def _grant_credits(client: TestClient, n: int, action_id: str = "seed-credits") -> None:
    """Earn `n` credits via /actions/session/add-past (seconds = n * 60)."""
    r = client.post(
        "/actions/session/add-past",
        json={
            "client_action_id": action_id,
            "state_vector_b64": "",
            "subject": "Seed",
            "seconds": n * 60,
            "ended_at_ms": 1_700_000_000_000,
        },
    )
    assert r.status_code == 200, r.text


def _grant_tokens(client: TestClient, n: int, action_prefix: str = "seed-tokens") -> None:
    """Earn `n` tokens by adding a session for `n` credits then converting all of them."""
    _grant_credits(client, n, action_id=f"{action_prefix}-credits")
    r = client.post(
        "/actions/convert", json={"client_action_id": f"{action_prefix}-convert", "state_vector_b64": "", "amount": n}
    )
    assert r.status_code == 200, r.text


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_pure_pull_returns_seed_state(client: TestClient) -> None:
    """First-time client posts an empty SV + empty update, gets the server's
    full doc back so it can bootstrap."""
    r = client.post("/sync", json={"state_vector_b64": "", "update_b64": ""})
    assert r.status_code == 200
    body = r.json()
    update = _unb64(body["update_b64"])
    casino = Casino.from_update(update)
    assert int(casino.balance["credits"]) == 0
    assert int(casino.balance["tokens"]) == 0
    # default prize catalog seeded
    assert len(casino.prizes) > 0


def test_round_trip_session_added_via_sync(client: TestClient) -> None:
    """Bootstrap, mutate a non-economy field locally, push to server, confirm canonical updated."""
    boot = client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()
    casino = Casino.from_update(_unb64(boot["update_b64"]))
    sv_before = casino.get_state()
    sm: Map = Map()
    casino.sessions["s1"] = sm
    sm["subject"] = "Biochem"
    sm["seconds"] = 1500
    sm["ended_at_ms"] = 1_700_000_000_000

    r = client.post(
        "/sync", json={"state_vector_b64": _b64(sv_before), "update_b64": _b64(casino.get_update(sv_before))}
    )
    assert r.status_code == 200, r.text

    # Reload state from server to confirm persistence.
    r2 = client.post("/sync", json={"state_vector_b64": "", "update_b64": ""})
    fresh = Casino.from_update(_unb64(r2.json()["update_b64"]))
    assert "s1" in fresh.sessions
    assert fresh.sessions["s1"]["subject"] == "Biochem"


def test_negative_credits_rejected_with_409(client: TestClient) -> None:
    boot = client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()
    casino = Casino.from_update(_unb64(boot["update_b64"]))
    sv_before = casino.get_state()
    casino.balance["credits"] = -5

    r = client.post(
        "/sync", json={"state_vector_b64": _b64(sv_before), "update_b64": _b64(casino.get_update(sv_before))}
    )
    assert r.status_code == 409
    body = r.json()
    assert body["rejection"]["rule"] == "credits_nonneg"
    assert "0" in body["rejection"]["message"]

    # Canonical was unchanged.
    fresh = Casino.from_update(
        _unb64(client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()["update_b64"])
    )
    assert int(fresh.balance["credits"]) == 0


def test_invalid_base64_rejected_with_400(client: TestClient) -> None:
    r = client.post("/sync", json={"state_vector_b64": "***not base64***", "update_b64": ""})
    assert r.status_code == 400


def test_two_clients_converge_via_server(client: TestClient) -> None:
    """Phone adds a session, syncs. Laptop bootstraps and reads the session."""
    boot = client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()
    phone = Casino.from_update(_unb64(boot["update_b64"]))
    sv_before = phone.get_state()
    sm: Map = Map()
    phone.sessions["s1"] = sm
    sm["subject"] = "Pharmacology"
    sm["seconds"] = 1800
    sm["ended_at_ms"] = 1_700_000_000_000
    client.post("/sync", json={"state_vector_b64": _b64(sv_before), "update_b64": _b64(phone.get_update(sv_before))})

    laptop_boot = client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()
    laptop = Casino.from_update(_unb64(laptop_boot["update_b64"]))
    assert "s1" in laptop.sessions
    assert laptop.sessions["s1"]["subject"] == "Pharmacology"


def test_me_returns_default_user_without_oidc(client: TestClient) -> None:
    """Without OIDC config, /me always returns the 'default' user."""
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json() == {"username": "default"}


def test_server_action_convert_is_idempotent_and_updates_doc(client: TestClient) -> None:
    _grant_credits(client, 10)

    body = {"client_action_id": "convert-1", "state_vector_b64": "", "amount": 4}
    first = client.post("/actions/convert", json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/actions/convert", json=body)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["event"]["id"] == first.json()["event"]["id"]

    fresh = Casino.from_update(
        _unb64(client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()["update_b64"])
    )
    assert int(fresh.balance["credits"]) == 6
    assert int(fresh.balance["tokens"]) == 4


def test_server_resolved_slots_updates_doc_and_logs(client: TestClient) -> None:
    _grant_credits(client, 5)

    r = client.post(
        "/casino/slots/spin", json={"client_action_id": "slots-1", "state_vector_b64": "", "wager_credits": 1}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event"]["action_type"] == "casino.slots.spin"
    assert body["game_event"]["source"] == "server_resolved"
    assert body["game_event"]["rng_version"] == "server-secrets-v1"

    fresh = Casino.from_update(
        _unb64(client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()["update_b64"])
    )
    assert int(fresh.balance["credits"]) == 4
    assert int(fresh.balance["tokens"]) == body["result"]["payout_tokens"]


def test_prize_redeem_server_action_updates_prize_log(client: TestClient) -> None:
    _grant_tokens(client, 100)

    r = client.post(
        "/actions/prize/redeem", json={"client_action_id": "redeem-1", "state_vector_b64": "", "prize_id": "p1"}
    )
    assert r.status_code == 200, r.text

    fresh = Casino.from_update(
        _unb64(client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()["update_b64"])
    )
    assert int(fresh.balance["tokens"]) == 70
    assert len(fresh.prize_log) == 1
    assert fresh.prize_log[0]["name"] == "Anime episode break"


def test_direct_economy_sync_rejected(client: TestClient) -> None:
    boot = client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()
    casino = Casino.from_update(_unb64(boot["update_b64"]))
    sv = casino.get_state()
    casino.balance["credits"] = 25

    r = client.post("/sync", json={"state_vector_b64": _b64(sv), "update_b64": _b64(casino.get_update(sv))})
    assert r.status_code == 409
    assert r.json()["rejection"]["rule"] == "server_authority"


def test_pre_alembic_user_db_is_baselined_and_upgraded(tmp_path: Path) -> None:
    db_path = tmp_path / "casino-default.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE doc (id INTEGER PRIMARY KEY, update_blob BLOB NOT NULL)")
        conn.execute("INSERT INTO doc (id, update_blob) VALUES (1, ?)", (Casino.empty().get_update(),))

    app = create_app(Settings(data_dir=tmp_path, frontend_dist_dir=tmp_path / "nonexistent_dist"))
    with TestClient(app) as c:
        # First request creates the DocStore for "default" and triggers
        # `alembic upgrade head` against the pre-Alembic schema baselined at 0001.
        r = c.post("/sync", json={"state_vector_b64": "", "update_b64": ""})
        assert r.status_code == 200, r.text

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
        assert conn.execute("SELECT count(*) FROM state_snapshots").fetchone() == (1,)


def test_users_have_isolated_state(tmp_path: Path) -> None:
    """Two users sharing one data_dir get separate, independent doc states."""
    app = create_app(Settings(data_dir=tmp_path, frontend_dist_dir=tmp_path / "nonexistent_dist"))
    dep = app.state.current_user_dep

    with TestClient(app) as client:
        # Alice earns 50 credits via a server action.
        app.dependency_overrides[dep] = lambda: "alice"
        _grant_credits(client, 50, action_id="alice-seed")

        alice_fresh = Casino.from_update(
            _unb64(client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()["update_b64"])
        )
        assert int(alice_fresh.balance["credits"]) == 50

        # Bob's state is independent — still at 0.
        app.dependency_overrides[dep] = lambda: "bob"
        boot_bob = client.post("/sync", json={"state_vector_b64": "", "update_b64": ""}).json()
        bob_casino = Casino.from_update(_unb64(boot_bob["update_b64"]))
        assert int(bob_casino.balance["credits"]) == 0
        assert len(bob_casino.sessions) == 0

        # Separate DB files confirm per-user storage.
        assert (tmp_path / "casino-alice.db").exists()
        assert (tmp_path / "casino-bob.db").exists()


@pytest.fixture
def ws_client(tmp_path: Path) -> TestClient:
    settings = Settings(data_dir=tmp_path, frontend_dist_dir=tmp_path / "nonexistent_dist")
    return TestClient(create_app(settings))


def test_ws_bootstrap_on_connect(ws_client: TestClient) -> None:
    """Server sends an 'accepted' bootstrap snapshot immediately on WS connect."""
    with ws_client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "accepted"
    update = _unb64(msg["update_b64"])
    casino = Casino.from_update(update)
    assert int(casino.balance["credits"]) == 0
    assert len(casino.prizes) > 0


def test_ws_sync_accepted(ws_client: TestClient) -> None:
    """Client pushes a non-economy mutation; server accepts and returns its state vector."""
    with ws_client.websocket_connect("/ws") as ws:
        boot = ws.receive_json()
        casino = Casino.from_update(_unb64(boot["update_b64"]))
        sv_before = casino.get_state()
        sm: Map = Map()
        casino.sessions["ws-1"] = sm
        sm["subject"] = "Anatomy"
        sm["seconds"] = 600
        sm["ended_at_ms"] = 1_700_000_000_000
        ws.send_json(
            {"type": "sync", "state_vector_b64": _b64(sv_before), "update_b64": _b64(casino.get_update(sv_before))}
        )
        msg = ws.receive_json()
    assert msg["type"] == "accepted"
    assert msg["state_vector_b64"]  # non-empty SV returned


def test_ws_sync_rejected(ws_client: TestClient) -> None:
    """Server rejects a sync that would make credits negative."""
    with ws_client.websocket_connect("/ws") as ws:
        boot = ws.receive_json()
        casino = Casino.from_update(_unb64(boot["update_b64"]))
        sv_before = casino.get_state()
        casino.balance["credits"] = -1
        ws.send_json(
            {"type": "sync", "state_vector_b64": _b64(sv_before), "update_b64": _b64(casino.get_update(sv_before))}
        )
        msg = ws.receive_json()
    assert msg["type"] == "rejected"
    assert msg["rule"] == "credits_nonneg"


def test_ws_server_push_to_other_tab(tmp_path: Path) -> None:
    """When one tab syncs successfully, other tabs receive a server_push."""
    settings = Settings(data_dir=tmp_path, frontend_dist_dir=tmp_path / "nonexistent_dist")
    app = create_app(settings)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws1, client.websocket_connect("/ws") as ws2:
        # Drain bootstrap messages.
        boot1 = ws1.receive_json()
        ws2.receive_json()

        casino = Casino.from_update(_unb64(boot1["update_b64"]))
        sv_before = casino.get_state()
        sm: Map = Map()
        casino.sessions["ws-push"] = sm
        sm["subject"] = "Biochem"
        sm["seconds"] = 600
        sm["ended_at_ms"] = 1_700_000_000_000
        ws1.send_json(
            {"type": "sync", "state_vector_b64": _b64(sv_before), "update_b64": _b64(casino.get_update(sv_before))}
        )
        # ws1 should receive accepted; ws2 should receive server_push.
        accepted = ws1.receive_json()
        push = ws2.receive_json()

    assert accepted["type"] == "accepted"
    assert push["type"] == "server_push"
    pushed_casino = Casino.from_update(_unb64(push["update_b64"]))
    assert "ws-push" in pushed_casino.sessions
    assert pushed_casino.sessions["ws-push"]["subject"] == "Biochem"


def test_ws_payload_too_large(ws_client: TestClient) -> None:
    """Server rejects payloads larger than the 4 MiB limit."""
    with ws_client.websocket_connect("/ws") as ws:
        ws.receive_json()  # drain bootstrap
        ws.send_json({"type": "sync", "state_vector_b64": "", "update_b64": "A" * (4 * 1024 * 1024 + 1)})
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert msg["code"] == 413


if __name__ == "__main__":
    pytest_bazel.main()
