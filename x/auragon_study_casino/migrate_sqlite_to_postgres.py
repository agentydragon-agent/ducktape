"""One-shot migration: per-user SQLite files → shared-schema Postgres.

Reads `casino-<username>.db` files from a directory and inserts every
row into a target Postgres database with `user_id=<username>` stamped
onto each. The target DB must already have the new schema (run alembic
upgrade head against it before invoking this script — the `SqlStore`
constructor does that automatically).

Usage:

    bb run --remote_executor="" //x/auragon_study_casino:migrate_sqlite_to_postgres -- \\
        --sqlite-dir ./casino-backup-20260516 \\
        --target-url 'postgresql+psycopg://studycasino:$PW@127.0.0.1:5432/studycasino'

`--dry-run` prints the row counts that would be migrated without
writing to Postgres.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from x.auragon_study_casino.models import (
    BalanceRow,
    BlackjackHandRow,
    GameEventRow,
    LedgerEventRow,
    PrizeLogRow,
    PrizeRow,
    SessionRow,
    StateSnapshotRow,
)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _ensure_target_schema(engine: Engine) -> None:
    """Run alembic upgrade head against the target."""
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        alembic_command.upgrade(cfg, "head")


logger = logging.getLogger(__name__)

_USER_FILE_RE = re.compile(r"^casino-(?P<username>[a-zA-Z0-9._@-]{1,64})\.db$")

# Tables to copy, in dependency order. Each entry is (table_name,
# columns-to-select-from-sqlite). We construct the ORM row in Postgres
# by zipping column names to values + stamping user_id.
_COPY_PLAN: list[tuple[str, type, list[str]]] = [
    (
        "balance",
        BalanceRow,
        # Pre-tenancy SQLite schema had `id`, `credits`, `tokens`. We drop `id`
        # (singleton row, always 1) and use the filename-derived username.
        ["credits", "tokens"],
    ),
    ("sessions", SessionRow, ["id", "subject", "seconds", "ended_at_ms"]),
    ("prizes", PrizeRow, ["id", "name", "cost"]),
    ("prize_log", PrizeLogRow, ["id", "name", "cost", "at_ms"]),
    (
        "game_events",
        GameEventRow,
        # NB: `id` is omitted intentionally — it's an autoincrement column
        # whose values would collide across users. Postgres assigns fresh
        # IDs; per-user audit ordering is preserved because rows are
        # inserted in source-ID order.
        [
            "client_event_id",
            "server_at_ms",
            "occurred_at_ms",
            "game",
            "event_type",
            "source",
            "wager_credits",
            "payout_tokens",
            "credits_before",
            "credits_after",
            "tokens_before",
            "tokens_after",
            "server_credits",
            "server_tokens",
            "outcome_json",
            "rules_version",
            "rng_version",
        ],
    ),
    (
        "ledger_events",
        LedgerEventRow,
        # `id` omitted — see note on game_events above.
        [
            "client_action_id",
            "server_at_ms",
            "action_type",
            "source",
            "rules_version",
            "rng_version",
            "credits_before",
            "credits_after",
            "tokens_before",
            "tokens_after",
            "details_json",
            "result_json",
        ],
    ),
    ("state_snapshots", StateSnapshotRow, ["id", "server_at_ms", "reason", "decoded_json", "note"]),
    (
        "blackjack_hands",
        BlackjackHandRow,
        [
            "id",
            "created_at_ms",
            "updated_at_ms",
            "status",
            "wager_credits",
            "current_wager_credits",
            "credits_before",
            "tokens_before",
            "shoe_json",
            "player_json",
            "dealer_json",
            "result_json",
        ],
    ),
]


# Postgres tables whose autoincrement `id` sequence must be reset after
# rows are inserted with explicit IDs — otherwise the next INSERT picks
# id=1 and collides.
_SEQUENCE_TABLES = ["game_events", "ledger_events", "state_snapshots"]


def _discover_users(sqlite_dir: Path) -> dict[str, Path]:
    """Return {username: db_path} for every `casino-<user>.db` in the dir."""
    out: dict[str, Path] = {}
    for db_path in sorted(sqlite_dir.iterdir()):
        m = _USER_FILE_RE.match(db_path.name)
        if not m:
            logger.info("skipping non-casino file: %s", db_path.name)
            continue
        out[m.group("username")] = db_path
    return out


def _copy_user(src: Session, dst: Session, username: str) -> dict[str, int]:
    """Copy every row from `src` (one user's SQLite DB) into `dst` (shared Postgres),
    stamping `user_id=username` on each. Returns counts per table."""
    counts: dict[str, int] = {}
    # Delete any pre-existing rows for this user so re-runs are idempotent.
    # Order matters: child tables first (none have FKs here, but we keep
    # dependency-friendly order regardless).
    for table_name, model, _cols in reversed(_COPY_PLAN):
        dst.execute(model.__table__.delete().where(model.user_id == username))  # type: ignore[attr-defined]
        logger.debug("cleared %s for %s", table_name, username)

    for table_name, model, cols in _COPY_PLAN:
        col_list = ", ".join(cols)
        rows = src.execute(text(f"SELECT {col_list} FROM {table_name}")).all()
        for row in rows:
            kwargs = dict(zip(cols, row, strict=True))
            kwargs["user_id"] = username
            dst.add(model(**kwargs))
        counts[table_name] = len(rows)
        logger.info("  %-16s %d rows", table_name, len(rows))
        dst.flush()

    return counts


def _reset_sequences(dst: Session) -> None:
    """Realign Postgres `id` sequences to `MAX(id)` so future inserts don't collide."""
    if dst.bind is None or dst.bind.dialect.name != "postgresql":
        return
    for table in _SEQUENCE_TABLES:
        dst.execute(
            text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))")
        )


def _verify(dst: Session, expected: dict[str, dict[str, int]]) -> None:
    """Cross-check: every (user, table) count in `expected` matches Postgres."""
    for username, counts in expected.items():
        for table_name, model, _cols in _COPY_PLAN:
            actual = dst.scalar(
                select(func.count()).select_from(model).where(model.user_id == username)  # type: ignore[attr-defined]
            )
            want = counts.get(table_name, 0)
            if actual != want:
                raise RuntimeError(f"mismatch for {username=} {table_name=}: copied {want}, found {actual}")
    logger.info("verification passed (counts match for every (user, table))")


def migrate(sqlite_dir: Path, target_url: str, *, dry_run: bool) -> None:
    users = _discover_users(sqlite_dir)
    if not users:
        raise SystemExit(f"no casino-*.db files in {sqlite_dir}")
    logger.info("found %d users: %s", len(users), ", ".join(sorted(users)))

    target_engine = create_engine(target_url)
    # Ensure target schema exists (no-op if already at head). Runs even on
    # dry-run — schema creation is a cheap, idempotent precondition; only
    # data writes are rolled back when dry_run is set.
    _ensure_target_schema(target_engine)

    expected_counts: dict[str, dict[str, int]] = {}
    for username, db_path in users.items():
        logger.info("[%s] from %s", username, db_path)
        src_engine = create_engine(f"sqlite:///{db_path}")
        try:
            with Session(src_engine) as src, Session(target_engine) as dst, dst.begin():
                counts = _copy_user(src, dst, username)
                expected_counts[username] = counts
                if dry_run:
                    dst.rollback()
                    logger.info("[%s] dry-run: rolling back transaction", username)
                else:
                    pass  # commit happens on `dst.begin()` context exit
        finally:
            src_engine.dispose()

    if not dry_run:
        with Session(target_engine) as dst, dst.begin():
            _reset_sequences(dst)
        with Session(target_engine) as dst:
            _verify(dst, expected_counts)

    target_engine.dispose()


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-dir", type=Path, required=True, help="Directory containing casino-*.db files")
    parser.add_argument(
        "--target-url",
        required=True,
        help="SQLAlchemy URL for the Postgres target, e.g. postgresql+psycopg://user:pass@host/db",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Read SQLite and roll back Postgres writes; print row counts only."
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    migrate(args.sqlite_dir, args.target_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
