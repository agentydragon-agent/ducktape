"""DocStore: validate-then-persist behaviour and round-trip via SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_bazel
from pycrdt import Map

from x.auragon_study_casino.doc_shape import Casino
from x.auragon_study_casino.store import Accepted, DocStore, Rejected


@pytest.fixture
def store(tmp_path: Path) -> DocStore:
    return DocStore(tmp_path / "casino.db")


def _client_with_initial_state(store: DocStore) -> Casino:
    """Bootstrap a client casino from the server's current update."""
    return Casino.from_update(store.get_update_for_client(None))


def test_seed_state_is_empty(store: DocStore) -> None:
    assert int(store.canonical.balance["credits"]) == 0
    assert int(store.canonical.balance["tokens"]) == 0


def _add_session(client: Casino, sid: str, subject: str, seconds: int, ended_at_ms: int = 1_700_000_000_000) -> None:
    sm: Map = Map()
    client.sessions[sid] = sm
    sm["subject"] = subject
    sm["seconds"] = seconds
    sm["ended_at_ms"] = ended_at_ms


def test_round_trip_accepts_valid_non_economy_update(store: DocStore) -> None:
    client = _client_with_initial_state(store)
    sv = client.get_state()
    _add_session(client, "s1", "Biochem", 1500)

    result = store.apply_client_update(client.get_update(sv), sv)
    assert isinstance(result, Accepted)
    assert "s1" in store.canonical.sessions
    assert store.canonical.sessions["s1"]["subject"] == "Biochem"


def test_direct_economy_sync_is_rejected(store: DocStore) -> None:
    client = _client_with_initial_state(store)
    sv = client.get_state()
    client.balance["credits"] = 50

    result = store.apply_client_update(client.get_update(sv), sv)
    assert isinstance(result, Rejected)
    assert result.rule == "server_authority"
    assert int(store.canonical.balance["credits"]) == 0


def test_negative_credits_update_is_rejected_and_canonical_unchanged(store: DocStore) -> None:
    """Validator catches `credits < 0` even though the server-authority rule
    would also reject this — the validator runs first so its rule is what the
    caller sees."""
    client = _client_with_initial_state(store)
    sv = client.get_state()
    client.balance["credits"] = -10

    result = store.apply_client_update(client.get_update(sv), sv)
    assert isinstance(result, Rejected)
    assert result.rule == "credits_nonneg"
    assert int(store.canonical.balance["credits"]) == 0


def test_canonical_persists_across_restart(tmp_path: Path) -> None:
    db = tmp_path / "casino.db"
    store_a = DocStore(db)
    client = _client_with_initial_state(store_a)
    sv = client.get_state()
    _add_session(client, "s1", "Anatomy", 2400)
    store_a.apply_client_update(client.get_update(sv), sv)

    store_b = DocStore(db)  # reopen
    assert "s1" in store_b.canonical.sessions
    assert store_b.canonical.sessions["s1"]["subject"] == "Anatomy"


def test_two_devices_concurrent_disjoint_updates_both_land(store: DocStore) -> None:
    """Two devices add disjoint non-economy sessions; both persist after sync.

    Per the /sync contract, `client_state_vector` is the *client's current*
    SV (so the server can compute a minimal diff back to the caller); the
    update bytes are produced against the client's last-known server SV
    (here `base_sv`). Conflating the two would still pass the assertions
    (Yjs is idempotent under double-application) but would not exercise
    the wire shape the production frontend uses.
    """
    base_sv = store.get_server_state_vector()
    base_update = store.get_update_for_client(None)

    phone = Casino.from_update(base_update)
    laptop = Casino.from_update(base_update)

    _add_session(phone, "phone-1", "Pharmacology", 3600)
    _add_session(laptop, "laptop-1", "Anatomy", 1500)

    r1 = store.apply_client_update(phone.get_update(base_sv), phone.get_state())
    assert isinstance(r1, Accepted)
    r2 = store.apply_client_update(laptop.get_update(base_sv), laptop.get_state())
    assert isinstance(r2, Accepted)

    canonical = store.canonical
    assert "phone-1" in canonical.sessions
    assert "laptop-1" in canonical.sessions
    assert canonical.sessions["phone-1"]["subject"] == "Pharmacology"
    assert canonical.sessions["laptop-1"]["subject"] == "Anatomy"


def test_server_never_persists_negative_tokens(store: DocStore) -> None:
    """The validator gate guarantees that no client update — however it
    arrives, however it merges — can land canonical with tokens < 0."""
    bad = _client_with_initial_state(store)
    bad_sv = bad.get_state()
    bad.balance["tokens"] = -50

    result = store.apply_client_update(bad.get_update(bad_sv), bad_sv)
    assert isinstance(result, Rejected)
    assert result.rule == "tokens_nonneg"
    assert int(store.canonical.balance["tokens"]) == 0


if __name__ == "__main__":
    pytest_bazel.main()
