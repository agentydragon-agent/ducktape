from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Literal

import pytest
import pytest_bazel

from finance.plaid.spend.portfolio_models import PortfolioView, SourceValuation
from finance.plaid.spend.valuation_history import record_snapshot


def _view(
    *,
    status: Literal["ready", "unavailable"] = "ready",
    assets: int | None = 125_000,
    net: int | None = 100_000,
) -> PortfolioView:
    as_of = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    return PortfolioView(
        status=status,
        assets_minor_units=assets,
        liabilities_minor_units=25_000 if assets is not None else None,
        excluded_minor_units=0 if assets is not None else None,
        net_minor_units=net,
        sources=[
            SourceValuation(
                name="plaid",
                status=status,
                amount_minor_units=assets,
                as_of=as_of if assets is not None else None,
                issues=[] if status == "ready" else ["A source observation is unavailable."],
            )
        ],
    )


def test_snapshot_upsert_is_idempotent_and_protects_ready_view(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    observed_at = datetime(2026, 1, 2, 4, 5, tzinfo=UTC)

    record_snapshot(path, "2026-01-02", "policy-a", _view(), observed_at)
    record_snapshot(path, "2026-01-02", "policy-a", _view(), observed_at)
    record_snapshot(
        path,
        "2026-01-02",
        "policy-a",
        _view(status="unavailable", assets=None, net=None),
        observed_at + timedelta(minutes=1),
    )

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT day, policy_revision, observed_at, view_json FROM valuation_snapshots"
        ).fetchone()
    assert row[0:2] == ("2026-01-02", "policy-a")
    assert row[2] == "2026-01-02T04:05:00.000000Z"
    assert PortfolioView.model_validate_json(row[3]).status == "ready"
    assert PortfolioView.model_validate_json(row[3]).net_minor_units == 100_000
    assert path.stat().st_mode & 0o777 == 0o600


def test_each_policy_revision_has_its_own_daily_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    observed_at = datetime(2026, 1, 2, 4, 5, tzinfo=UTC)

    record_snapshot(path, "2026-01-02", "policy-a", _view(), observed_at)
    record_snapshot(path, "2026-01-02", "policy-b", _view(net=90_000), observed_at)

    with sqlite3.connect(path) as connection:
        revisions = connection.execute(
            "SELECT policy_revision FROM valuation_snapshots ORDER BY policy_revision"
        ).fetchall()
    assert revisions == [("policy-a",), ("policy-b",)]


def test_store_has_only_aggregate_view_fields(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    record_snapshot(path, "2026-01-02", "policy-a", _view(), datetime(2026, 1, 2, 4, 5, tzinfo=UTC))

    with sqlite3.connect(path) as connection:
        stored = connection.execute("SELECT view_json FROM valuation_snapshots").fetchone()[0]

    assert "assets_minor_units" in stored
    assert "as_of" in stored
    assert "account_id" not in stored
    assert "transaction_id" not in stored
    assert "api_secret" not in stored


@pytest.mark.parametrize("day", ["2026-1-2", "2026-02-30"])
def test_day_must_be_a_real_iso_calendar_date(tmp_path: Path, day: str) -> None:
    with pytest.raises(ValueError):
        record_snapshot(
            tmp_path / "history.sqlite3", day, "policy-a", _view(), datetime(2026, 1, 2, 4, 5, tzinfo=UTC)
        )


def test_observation_time_must_be_timezone_aware(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        record_snapshot(tmp_path / "history.sqlite3", "2026-01-02", "policy-a", _view(), datetime(2026, 1, 2))


if __name__ == "__main__":
    pytest_bazel.main()
