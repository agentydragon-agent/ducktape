"""Private SQLite storage for daily aggregate portfolio valuations."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

from finance.plaid.spend.portfolio_models import PortfolioView


def _validate_day(day: str) -> None:
    parsed = date.fromisoformat(day)
    if parsed.isoformat() != day:
        raise ValueError("day must be an ISO local calendar date")


def _observed_at(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def record_snapshot(
    path: Path,
    day: str,
    policy_revision: str,
    view: PortfolioView,
    observed_at: datetime,
) -> None:
    """Insert or refresh one aggregate valuation for a local day and policy revision.

    The typed view contains only aggregate amounts, source ages and fixed source status
    messages. A failed retry cannot replace a ready valuation already stored for the same key.
    """
    _validate_day(day)
    if not policy_revision:
        raise ValueError("policy_revision must not be empty")
    observed_at_text = _observed_at(observed_at)
    view_json = json.dumps(view.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    os.chmod(path, 0o600)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS valuation_snapshots (
                    day TEXT NOT NULL,
                    policy_revision TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    view_json TEXT NOT NULL,
                    PRIMARY KEY (day, policy_revision)
                ) WITHOUT ROWID
                """
            )
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT view_json FROM valuation_snapshots WHERE day = ? AND policy_revision = ?",
                (day, policy_revision),
            ).fetchone()
            if existing is not None:
                previous_view = PortfolioView.model_validate_json(existing[0])
                if previous_view.status == "ready" and view.status != "ready":
                    return
            connection.execute(
                """
                INSERT INTO valuation_snapshots (day, policy_revision, observed_at, view_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (day, policy_revision) DO UPDATE SET
                    observed_at = excluded.observed_at,
                    view_json = excluded.view_json
                """,
                (day, policy_revision, observed_at_text, view_json),
            )


