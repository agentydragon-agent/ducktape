from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
import pytest_bazel
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from plaid_utils.link_profiles import LinkProfile
from plaid_utils.link_store import PlaidLinkStorage
from plaid_utils.read_model import read_budget_transactions, read_current_cash_balances, read_current_holdings
from plaid_utils.schema import TransactionRow, async_session_factory
from third_party.containers.rlocations import POSTGRES_18, RYUK
from util.oci import load_oci_image
from util.testing.postgres import force_drop_database


@pytest.fixture(scope="session", autouse=True)
def _preload_postgres_images() -> None:
    load_oci_image(RYUK)
    load_oci_image(POSTGRES_18)


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer]:
    container = PostgresContainer(image=POSTGRES_18.tag, username="postgres", password="postgres", dbname="postgres")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def postgres_admin_url(postgres_container: PostgresContainer) -> str:
    host = postgres_container.get_container_host_ip()
    port = int(postgres_container.get_exposed_port(5432))
    return f"postgresql+asyncpg://postgres:postgres@{host}:{port}/postgres"


@pytest_asyncio.fixture
async def db_url(postgres_admin_url: str, request: pytest.FixtureRequest) -> AsyncGenerator[str]:
    db_name = re.sub(r"[^a-z0-9]", "_", request.node.name.lower())[:45].rstrip("_") or "plaid_test"
    admin_engine = create_async_engine(postgres_admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()
    try:
        yield make_url(postgres_admin_url).set(database=db_name).render_as_string(hide_password=False)
    finally:
        await force_drop_database(postgres_admin_url, db_name)


@pytest_asyncio.fixture
async def storage(db_url: str) -> AsyncGenerator[PlaidLinkStorage]:
    store = await PlaidLinkStorage.initialize(db_url)
    try:
        yield store
    finally:
        await store.close()


@pytest_asyncio.fixture
async def session_factory(db_url: str) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine, factory = async_session_factory(db_url)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _add_link(storage: PlaidLinkStorage, *, item_id: str = "item-investments") -> None:
    await storage.upsert_link(
        item_id=item_id,
        access_token_secret=f"{item_id}-token",
        link_profile=LinkProfile.INVESTMENTS_FULL,
        products_requested=["investments"],
        institution_id="ins_investments",
        institution_name="Investment Test",
        label=None,
    )


async def test_read_current_cash_balances_returns_latest_selected_usd_snapshot(
    storage: PlaidLinkStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _add_link(storage, item_id="item-cash")
    await storage.apply_accounts(
        item_id="item-cash",
        accounts=[
            {
                "account_id": "checking",
                "name": "Checking",
                "type": "depository",
                "balances": {"available": 100.0, "current": 110.0, "limit": None, "iso_currency_code": "USD"},
            },
            {
                "account_id": "cad",
                "name": "CAD",
                "type": "depository",
                "balances": {"available": 5.0, "current": 6.0, "limit": None, "iso_currency_code": "CAD"},
            },
        ],
        captured_at=datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
    )
    await storage.apply_accounts(
        item_id="item-cash",
        accounts=[
            {
                "account_id": "checking",
                "name": "Checking",
                "type": "depository",
                "balances": {"available": 150.0, "current": 160.0, "limit": None, "iso_currency_code": "USD"},
            }
        ],
        captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )

    balances = await read_current_cash_balances(
        session_factory=session_factory, account_ids=("checking", "cad", "missing")
    )

    assert [balance.account_id for balance in balances] == ["checking"]
    assert balances[0].current == 160.0
    assert balances[0].available == 150.0
    assert balances[0].institution_name == "Investment Test"


async def test_read_current_holdings_returns_latest_selected_usd_holdings(
    storage: PlaidLinkStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _add_link(storage, item_id="item-investments")
    await storage.apply_accounts(
        item_id="item-investments",
        accounts=[
            {
                "account_id": "brokerage",
                "name": "Brokerage",
                "type": "investment",
                "balances": {"available": None, "current": 1000.0, "limit": None, "iso_currency_code": "USD"},
            }
        ],
        captured_at=datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
    )
    securities = [
        {"security_id": "sec-voo", "name": "Vanguard 500", "ticker_symbol": "VOO", "type": "etf", "raw_json": {}},
        {"security_id": "sec-cad", "name": "CAD Fund", "ticker_symbol": "CADF", "type": "etf", "raw_json": {}},
    ]
    await storage.apply_holdings(
        item_id="item-investments",
        securities=securities,
        holdings=[
            {
                "account_id": "brokerage",
                "security_id": "sec-voo",
                "quantity": 2.0,
                "cost_basis": 700.0,
                "institution_price": 400.0,
                "institution_value": 800.0,
                "iso_currency_code": "USD",
            },
            {
                "account_id": "brokerage",
                "security_id": "sec-cad",
                "quantity": 1.0,
                "cost_basis": 10.0,
                "institution_price": 11.0,
                "institution_value": 11.0,
                "iso_currency_code": "CAD",
            },
        ],
        captured_at=datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
    )
    await storage.apply_holdings(
        item_id="item-investments",
        securities=securities,
        holdings=[
            {
                "account_id": "brokerage",
                "security_id": "sec-voo",
                "quantity": 3.0,
                "cost_basis": 900.0,
                "institution_price": 450.0,
                "institution_value": 1350.0,
                "iso_currency_code": "USD",
            }
        ],
        captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )

    holdings = await read_current_holdings(session_factory=session_factory, account_ids=("brokerage", "missing"))

    assert [holding.security_id for holding in holdings] == ["sec-voo"]
    assert holdings[0].ticker_symbol == "VOO"
    assert holdings[0].quantity == 3.0
    assert holdings[0].institution_value == 1350.0
    assert holdings[0].cost_basis == 900.0


async def test_read_budget_transactions_returns_ordered_projected_orm_rows(
    storage: PlaidLinkStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _add_link(storage, item_id="item-budget")
    await storage.apply_accounts(
        item_id="item-budget",
        accounts=[
            {
                "account_id": "checking",
                "name": "Checking",
                "type": "depository",
                "balances": {"available": 100.0, "current": 100.0, "limit": None, "iso_currency_code": "USD"},
            },
            {
                "account_id": "other-account",
                "name": "Other",
                "type": "depository",
                "balances": {"available": 50.0, "current": 50.0, "limit": None, "iso_currency_code": "USD"},
            },
        ],
        captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )
    await storage.reconcile_transactions(
        item_id="item-budget",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 6, 30),
        captured_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        transactions=[
            {
                "transaction_id": "later",
                "account_id": "checking",
                "date": "2026-06-02",
                "amount": 25.0,
                "iso_currency_code": "USD",
                "name": "CARD STORE",
                "merchant_name": "Store",
                "pending": False,
                "personal_finance_category": {"primary": "GENERAL_MERCHANDISE", "detailed": "GENERAL_MERCHANDISE"},
                "unused_large_blob": "x" * 2000,
            },
            {
                "transaction_id": "earlier",
                "account_id": "checking",
                "date": "2026-06-01",
                "amount": -100.0,
                "iso_currency_code": "USD",
                "name": "PAYROLL",
                "merchant_name": None,
                "pending": False,
                "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"},
                "unused_large_blob": "y" * 2000,
            },
            {
                "transaction_id": "pending",
                "account_id": "checking",
                "date": "2026-06-03",
                "amount": 10.0,
                "iso_currency_code": "USD",
                "name": "PENDING",
                "merchant_name": "Pending",
                "pending": True,
                "personal_finance_category": {"primary": "GENERAL_MERCHANDISE", "detailed": "GENERAL_MERCHANDISE"},
            },
            {
                "transaction_id": "removed",
                "account_id": "checking",
                "date": "2026-06-04",
                "amount": 11.0,
                "iso_currency_code": "USD",
                "name": "REMOVED",
                "merchant_name": "Removed",
                "pending": False,
                "personal_finance_category": {"primary": "GENERAL_MERCHANDISE", "detailed": "GENERAL_MERCHANDISE"},
            },
            {
                "transaction_id": "other-account",
                "account_id": "other-account",
                "date": "2026-06-05",
                "amount": 12.0,
                "iso_currency_code": "USD",
                "name": "OTHER",
                "merchant_name": "Other",
                "pending": False,
                "personal_finance_category": {"primary": "GENERAL_MERCHANDISE", "detailed": "GENERAL_MERCHANDISE"},
            },
        ],
    )
    await storage.upsert_link(
        item_id="item-revoked",
        access_token_secret="item-revoked-token",
        link_profile=LinkProfile.CASHFLOW,
        products_requested=["transactions"],
        institution_id="ins_revoked",
        institution_name="Revoked Test",
        label=None,
        status="revoked",
    )
    await storage.apply_accounts(
        item_id="item-revoked",
        accounts=[
            {
                "account_id": "revoked-account",
                "name": "Revoked",
                "type": "depository",
                "balances": {"available": 10.0, "current": 10.0, "limit": None, "iso_currency_code": "USD"},
            }
        ],
        captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )
    await storage.reconcile_transactions(
        item_id="item-revoked",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        captured_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        transactions=[
            {
                "transaction_id": "revoked",
                "account_id": "revoked-account",
                "date": "2026-06-02",
                "amount": 13.0,
                "iso_currency_code": "USD",
                "name": "REVOKED",
                "merchant_name": "Revoked",
                "pending": False,
                "personal_finance_category": {"primary": "GENERAL_MERCHANDISE", "detailed": "GENERAL_MERCHANDISE"},
            }
        ],
    )
    async with session_factory() as session:
        await session.execute(text("UPDATE transactions SET removed = true WHERE transaction_id = 'removed'"))
        await session.commit()

    transactions = await read_budget_transactions(
        session_factory=session_factory,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        account_ids=("checking",),
    )

    assert [transaction.transaction_id for transaction in transactions] == ["earlier", "later"]
    assert all(isinstance(transaction, TransactionRow) for transaction in transactions)
    assert transactions[0].amount == -100.0
    assert transactions[0].pfc_primary == "INCOME"
    assert transactions[0].pfc_detailed == "INCOME_WAGES"
    assert transactions[1].merchant_name == "Store"
    assert "raw_json" in inspect(transactions[0]).unloaded


if __name__ == "__main__":
    pytest_bazel.main()
