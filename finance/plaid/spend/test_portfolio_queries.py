"""Behavioral coverage for the shared portfolio snapshot selectors."""

from datetime import UTC, datetime, timedelta

import pytest_bazel
from sqlalchemy import insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from finance.plaid.db.models import AccountRow, BalanceSnapshotRow, HoldingSnapshotRow, LinkRow, SecurityRow
from finance.plaid.spend.portfolio_queries import select_account_balances, select_holding_batches


def test_snapshot_selectors_drop_sold_positions_and_respect_account_liveness(postgres_engine: Engine) -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    earlier = now - timedelta(hours=1)
    with postgres_engine.begin() as connection:
        connection.execute(
            insert(LinkRow),
            [
                {
                    "item_id": item,
                    "institution_name": "Synthetic institution",
                    "products_requested": [],
                    "products_authorized": [],
                    "products_billed": [],
                    "status": status,
                    "access_token_secret": "fake-secret-reference",
                    "created_at": now,
                    "updated_at": now,
                }
                for item, status in [("fake-active", "active"), ("fake-inactive", "inactive")]
            ],
        )
        connection.execute(
            insert(AccountRow),
            [
                {
                    "account_id": account,
                    "item_id": item,
                    "name": "Synthetic account",
                    "type": "investment",
                    "iso_currency_code": "USD",
                    "raw_json": {},
                    "detached_at": detached,
                    "updated_at": now,
                }
                for account, item, detached in [
                    ("fake-selected", "fake-active", None),
                    ("fake-no-balance", "fake-active", None),
                    ("fake-unselected", "fake-active", None),
                    ("fake-detached", "fake-active", now),
                    ("fake-inactive", "fake-inactive", None),
                ]
            ],
        )
        connection.execute(
            insert(BalanceSnapshotRow),
            [
                {
                    "account_id": account,
                    "item_id": item,
                    "captured_at": captured,
                    "current": amount,
                    "iso_currency_code": "USD",
                }
                for account, item in [
                    ("fake-selected", "fake-active"),
                    ("fake-unselected", "fake-active"),
                    ("fake-detached", "fake-active"),
                    ("fake-inactive", "fake-inactive"),
                ]
                for captured, amount in [(earlier, 10), (now, 20), (now, 30)]
            ],
        )
        connection.execute(
            insert(SecurityRow),
            [
                {
                    "security_id": security,
                    "name": security,
                    "ticker_symbol": ticker,
                    "type": "equity",
                    "raw_json": {},
                    "updated_at": now,
                }
                for security, ticker in [("fake-sold", "SOLD"), ("fake-held", "HELD")]
            ],
        )
        connection.execute(
            insert(HoldingSnapshotRow),
            [
                {
                    "account_id": account,
                    "item_id": item,
                    "security_id": security,
                    "captured_at": captured,
                    "institution_value": 30,
                    "iso_currency_code": "USD",
                    "raw_json": {},
                }
                for account, item, security, captured in [
                    ("fake-selected", "fake-active", "fake-sold", earlier),
                    ("fake-selected", "fake-active", "fake-held", earlier),
                    ("fake-selected", "fake-active", "fake-held", now),
                    ("fake-unselected", "fake-active", "fake-held", now),
                    ("fake-detached", "fake-active", "fake-held", now),
                    ("fake-inactive", "fake-inactive", "fake-held", now),
                ]
            ],
        )
        selected = ["fake-selected", "fake-no-balance", "fake-detached", "fake-inactive"]
        balances = connection.execute(select_account_balances(selected)).mappings().all()
        holdings = connection.execute(select_holding_batches(selected)).mappings().all()
        assert {row["account_id"]: row["current"] for row in balances} == {"fake-selected": 30, "fake-no-balance": None}
        assert [(row["account_id"], row["security_id"], row["ticker"]) for row in holdings] == [
            ("fake-selected", "fake-held", "HELD")
        ]
        assert connection.execute(select_account_balances([])).all() == []
        assert connection.execute(select_holding_batches([])).all() == []


def test_selectors_bind_hostile_values() -> None:
    selector = "fake-account'); DROP TABLE accounts; --"
    for statement in [select_account_balances([selector]), select_holding_batches([selector])]:
        compiled = statement.compile(dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True})
        assert selector not in str(compiled)
        assert selector in compiled.params.values()


if __name__ == "__main__":
    pytest_bazel.main()
