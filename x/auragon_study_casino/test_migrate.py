"""Round-trip test for migrate_sqlite_to_postgres.

Uses SQLite as both source and target so the test is hermetic — the only
Postgres-specific bit (sequence reset) is dialect-guarded in the script
and a no-op on SQLite. Schema-correctness on Postgres is verified
separately in the cluster (the migration script is run once during the
SQLite→CNPG cutover).
"""

from __future__ import annotations

from pathlib import Path

import pytest_bazel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from x.auragon_study_casino.migrate_sqlite_to_postgres import migrate
from x.auragon_study_casino.models import BalanceRow, GameEventRow, LedgerEventRow, PrizeLogRow, PrizeRow, SessionRow


def _write_legacy_sqlite(path: Path) -> None:
    """Write a fixture SQLite DB matching the pre-tenancy (post-0004) schema."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE balance (id INTEGER PRIMARY KEY, credits INTEGER, tokens INTEGER)"))
        conn.execute(
            text("CREATE TABLE sessions (id TEXT PRIMARY KEY, subject TEXT, seconds INTEGER, ended_at_ms INTEGER)")
        )
        conn.execute(text("CREATE TABLE prizes (id TEXT PRIMARY KEY, name TEXT, cost INTEGER)"))
        conn.execute(text("CREATE TABLE prize_log (id TEXT PRIMARY KEY, name TEXT, cost INTEGER, at_ms INTEGER)"))
        conn.execute(
            text(
                "CREATE TABLE game_events ("
                "id INTEGER PRIMARY KEY, client_event_id TEXT, server_at_ms INTEGER, "
                "occurred_at_ms INTEGER, game TEXT, event_type TEXT, source TEXT, "
                "wager_credits INTEGER, payout_tokens INTEGER, "
                "credits_before INTEGER, credits_after INTEGER, "
                "tokens_before INTEGER, tokens_after INTEGER, "
                "server_credits INTEGER, server_tokens INTEGER, "
                "outcome_json TEXT, rules_version TEXT, rng_version TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE ledger_events ("
                "id INTEGER PRIMARY KEY, client_action_id TEXT, server_at_ms INTEGER, "
                "action_type TEXT, source TEXT, rules_version TEXT, rng_version TEXT, "
                "credits_before INTEGER, credits_after INTEGER, "
                "tokens_before INTEGER, tokens_after INTEGER, "
                "details_json TEXT, result_json TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE state_snapshots ("
                "id INTEGER PRIMARY KEY, server_at_ms INTEGER, reason TEXT, "
                "decoded_json TEXT, note TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE blackjack_hands ("
                "id TEXT PRIMARY KEY, created_at_ms INTEGER, updated_at_ms INTEGER, "
                "status TEXT, wager_credits INTEGER, current_wager_credits INTEGER, "
                "credits_before INTEGER, tokens_before INTEGER, "
                "shoe_json TEXT, player_json TEXT, dealer_json TEXT, result_json TEXT)"
            )
        )
        # Seed some data
        conn.execute(text("INSERT INTO balance (id, credits, tokens) VALUES (1, 42, 17)"))
        conn.execute(
            text("INSERT INTO sessions (id, subject, seconds, ended_at_ms) VALUES ('s1', 'Math', 1500, 1700000000000)")
        )
        conn.execute(text("INSERT INTO prizes (id, name, cost) VALUES ('p1', 'Tea', 5)"))
        conn.execute(text("INSERT INTO prize_log (id, name, cost, at_ms) VALUES ('r1', 'Tea', 5, 1700000000000)"))
        conn.execute(
            text(
                "INSERT INTO ledger_events ("
                "id, client_action_id, server_at_ms, action_type, source, rules_version, "
                "rng_version, credits_before, credits_after, tokens_before, tokens_after, "
                "details_json, result_json) VALUES ("
                "1, 'a1', 1700000000000, 'session.complete', 'server_action', 'v1', "
                "NULL, 0, 42, 0, 0, '{}', '{}')"
            )
        )
    engine.dispose()


def test_migrate_copies_rows_and_stamps_user_id(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_legacy_sqlite(source_dir / "casino-alice.db")
    _write_legacy_sqlite(source_dir / "casino-bob.db")
    # A non-matching file should be ignored.
    (source_dir / "notes.txt").write_text("ignored")

    target_url = f"sqlite:///{tmp_path / 'target.db'}"

    migrate(source_dir, target_url, dry_run=False)

    engine = create_engine(target_url)
    with Session(engine) as s:
        alice_balance = s.get(BalanceRow, "alice")
        assert alice_balance is not None
        assert alice_balance.credits == 42
        assert alice_balance.tokens == 17
        bob_balance = s.get(BalanceRow, "bob")
        assert bob_balance is not None
        assert bob_balance.credits == 42

        # Same `id` ("s1") in two SQLite DBs maps to two rows scoped by user_id.
        alice_sessions = list(s.scalars(SessionRow.__table__.select().where(SessionRow.user_id == "alice")))
        bob_sessions = list(s.scalars(SessionRow.__table__.select().where(SessionRow.user_id == "bob")))
        assert len(alice_sessions) == 1
        assert len(bob_sessions) == 1

        # Cross-user data isolation in ledger_events / game_events / prize_log.
        assert s.query(LedgerEventRow).filter(LedgerEventRow.user_id == "alice").count() == 1
        assert s.query(LedgerEventRow).filter(LedgerEventRow.user_id == "bob").count() == 1
        assert s.query(PrizeRow).filter(PrizeRow.user_id == "alice").count() == 1
        assert s.query(PrizeLogRow).filter(PrizeLogRow.user_id == "bob").count() == 1
        # game_events was empty in the source; should be empty per user.
        assert s.query(GameEventRow).filter(GameEventRow.user_id == "alice").count() == 0
    engine.dispose()


def test_migrate_dry_run_writes_nothing(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_legacy_sqlite(source_dir / "casino-alice.db")

    target_url = f"sqlite:///{tmp_path / 'target.db'}"

    migrate(source_dir, target_url, dry_run=True)

    engine = create_engine(target_url)
    with Session(engine) as s:
        # The target was created (SqlStore ran migrations), but no data was committed.
        # The lazy-seed only runs on first SqlStore access; here we just ran
        # `SqlStore(target_url)` once which doesn't seed any user.
        assert s.query(BalanceRow).count() == 0
        assert s.query(SessionRow).count() == 0
    engine.dispose()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    """Running the migration twice produces the same final state (no duplicate rows)."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    _write_legacy_sqlite(source_dir / "casino-alice.db")

    target_url = f"sqlite:///{tmp_path / 'target.db'}"

    migrate(source_dir, target_url, dry_run=False)
    migrate(source_dir, target_url, dry_run=False)

    engine = create_engine(target_url)
    with Session(engine) as s:
        assert s.query(BalanceRow).filter(BalanceRow.user_id == "alice").count() == 1
        assert s.query(SessionRow).filter(SessionRow.user_id == "alice").count() == 1
        assert s.query(LedgerEventRow).filter(LedgerEventRow.user_id == "alice").count() == 1
    engine.dispose()


if __name__ == "__main__":
    pytest_bazel.main()
