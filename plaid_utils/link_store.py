"""Postgres storage for the Plaid self-contained link service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from plaid_utils.link_profiles import LinkProfile

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalise_db_url(db_url: str) -> str:
    return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _run_alembic_migrations(conn: Any) -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.attributes["connection"] = conn
    alembic_command.upgrade(cfg, "head")


class _Base(DeclarativeBase):
    pass


class _LinkRow(_Base):
    __tablename__ = "links"

    item_id: Mapped[str] = mapped_column(String, primary_key=True)
    institution_id: Mapped[str | None] = mapped_column(String, nullable=True)
    institution_name: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    link_profile: Mapped[str] = mapped_column(String, nullable=False)
    products_requested: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    products_authorized: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    products_billed: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    access_token_secret: Mapped[str] = mapped_column(String, nullable=False)
    transactions_cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    transactions_update_status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class _AccountRow(_Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("links.item_id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    official_name: Mapped[str | None] = mapped_column(String, nullable=True)
    mask: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    subtype: Mapped[str | None] = mapped_column(String, nullable=True)
    iso_currency_code: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class _TransactionRow(_Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.account_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("links.item_id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    iso_currency_code: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String, nullable=True)
    pending: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pending_transaction_id: Mapped[str | None] = mapped_column(String, nullable=True)
    pfc_primary: Mapped[str | None] = mapped_column(String, nullable=True)
    pfc_detailed: Mapped[str | None] = mapped_column(String, nullable=True)
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class _BalanceSnapshotRow(_Base):
    __tablename__ = "balance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.account_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("links.item_id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available: Mapped[float | None] = mapped_column(Float, nullable=True)
    current: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    iso_currency_code: Mapped[str | None] = mapped_column(String, nullable=True)


class _SecurityRow(_Base):
    __tablename__ = "securities"

    security_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    ticker_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    iso_currency_code: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class _HoldingSnapshotRow(_Base):
    __tablename__ = "holding_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.account_id"), nullable=False)
    security_id: Mapped[str] = mapped_column(String, ForeignKey("securities.security_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("links.item_id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_basis: Mapped[float | None] = mapped_column(Float, nullable=True)
    institution_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    institution_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    iso_currency_code: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class _InvestmentTransactionRow(_Base):
    __tablename__ = "investment_transactions"

    investment_transaction_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.account_id"), nullable=False)
    security_id: Mapped[str | None] = mapped_column(String, nullable=True)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("links.item_id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float | None] = mapped_column(Float, nullable=True)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    subtype: Mapped[str | None] = mapped_column(String, nullable=True)
    iso_currency_code: Mapped[str | None] = mapped_column(String, nullable=True)
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class _LiabilityCreditSnapshotRow(_Base):
    __tablename__ = "liability_credit_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.account_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("links.item_id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class _LiabilityMortgageSnapshotRow(_Base):
    __tablename__ = "liability_mortgage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.account_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("links.item_id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class _LiabilityStudentSnapshotRow(_Base):
    __tablename__ = "liability_student_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("accounts.account_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String, ForeignKey("links.item_id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class _SyncRunRow(_Base):
    __tablename__ = "sync_runs"

    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=True), primary_key=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str | None] = mapped_column(String, nullable=True)
    configured_windows: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class _PlaidApiEventRow(_Base):
    __tablename__ = "plaid_api_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sync_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True, native_uuid=True), nullable=True)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str | None] = mapped_column(String, nullable=True)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


@dataclass(frozen=True)
class StoredLink:
    item_id: str
    label: str | None
    institution_id: str | None
    institution_name: str | None
    link_profile: LinkProfile
    products_requested: list[str]
    products_authorized: list[str]
    products_billed: list[str]
    status: str
    access_token_secret: str
    last_synced_at: datetime | None


@dataclass(frozen=True)
class ApiEvent:
    endpoint: str
    status: str
    request_json: dict[str, Any]
    response_json: dict[str, Any] | None = None
    sync_run_id: UUID | None = None
    item_id: str | None = None
    account_id: str | None = None
    request_id: str | None = None
    duration_ms: int | None = None
    error_type: str | None = None
    error_code: str | None = None


class PlaidLinkStorage:
    """Async PostgreSQL storage for Plaid link metadata and mirrored data."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine) -> None:
        self._session_factory = session_factory
        self._engine = engine

    @classmethod
    async def initialize(cls, db_url: str) -> PlaidLinkStorage:
        engine = create_async_engine(_normalise_db_url(db_url))
        async with engine.begin() as conn:
            await conn.run_sync(_run_alembic_migrations)
        return cls(async_sessionmaker(engine, expire_on_commit=False), engine)

    async def close(self) -> None:
        await self._engine.dispose()

    async def upsert_link(
        self,
        *,
        item_id: str,
        access_token_secret: str,
        link_profile: LinkProfile,
        products_requested: list[str],
        institution_id: str | None,
        institution_name: str | None,
        label: str | None,
        products_authorized: list[str] | None = None,
        products_billed: list[str] | None = None,
        status: str = "active",
    ) -> StoredLink:
        now = _utcnow()
        values = {
            "item_id": item_id,
            "institution_id": institution_id,
            "institution_name": institution_name,
            "label": label,
            "link_profile": link_profile.value,
            "products_requested": products_requested,
            "products_authorized": products_authorized or products_requested,
            "products_billed": products_billed or [],
            "status": status,
            "access_token_secret": access_token_secret,
            "updated_at": now,
        }
        insert_values = values | {"created_at": now}
        update_values = {k: v for k, v in values.items() if k != "item_id"}
        stmt = (
            pg_insert(_LinkRow)
            .values(**insert_values)
            .on_conflict_do_update(index_elements=["item_id"], set_=update_values)
            .returning(_LinkRow)
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one()
            await session.commit()
        return _stored_link(row)

    async def mark_link_revoked(self, item_id: str) -> None:
        async with self._session_factory() as session:
            row = await session.get(_LinkRow, item_id)
            if row is not None:
                row.status = "revoked"
                row.updated_at = _utcnow()
                await session.commit()

    async def mark_link_update_succeeded(
        self, *, item_id: str, link_profile: LinkProfile, products_requested: list[str]
    ) -> StoredLink | None:
        async with self._session_factory() as session:
            row = await session.get(_LinkRow, item_id)
            if row is None:
                return None
            row.link_profile = link_profile.value
            row.products_requested = products_requested
            row.products_authorized = _merge_products(list(row.products_authorized), products_requested)
            row.status = "active"
            row.updated_at = _utcnow()
            await session.commit()
            return _stored_link(row)

    async def list_active_links(self) -> list[StoredLink]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(_LinkRow).where(_LinkRow.status != "revoked").order_by(_LinkRow.institution_name)
                )
            ).scalars()
            return [_stored_link(r) for r in rows]

    async def get_link(self, item_id: str) -> StoredLink | None:
        async with self._session_factory() as session:
            row = await session.get(_LinkRow, item_id)
            return _stored_link(row) if row is not None else None

    async def begin_sync_run(self, *, trigger: str, item_id: str | None, configured_windows: dict[str, Any]) -> UUID:
        run_id = uuid4()
        async with self._session_factory() as session:
            if item_id is not None:
                running = await session.execute(
                    select(func.count())
                    .select_from(_SyncRunRow)
                    .where(_SyncRunRow.item_id == item_id, _SyncRunRow.status == "running")
                )
                if running.scalar_one() > 0:
                    raise RuntimeError(f"sync already running for Plaid item {item_id}")
            session.add(
                _SyncRunRow(
                    run_id=run_id,
                    trigger=trigger,
                    mode="v0_full_refresh",
                    item_id=item_id,
                    configured_windows=configured_windows,
                    status="running",
                    started_at=_utcnow(),
                )
            )
            await session.commit()
        return run_id

    async def finish_sync_run(self, run_id: UUID, *, status: str, error_summary: str | None = None) -> None:
        async with self._session_factory() as session:
            row = await session.get(_SyncRunRow, run_id)
            if row is None:
                raise ValueError(f"sync run not found: {run_id}")
            row.status = status
            row.finished_at = _utcnow()
            row.error_summary = error_summary
            await session.commit()

    async def record_api_event(self, event: ApiEvent) -> None:
        async with self._session_factory() as session:
            session.add(
                _PlaidApiEventRow(
                    sync_run_id=event.sync_run_id,
                    endpoint=event.endpoint,
                    item_id=event.item_id,
                    account_id=event.account_id,
                    request_id=event.request_id,
                    status=event.status,
                    duration_ms=event.duration_ms,
                    error_type=event.error_type,
                    error_code=event.error_code,
                    request_json=event.request_json,
                    response_json=event.response_json,
                    created_at=_utcnow(),
                )
            )
            await session.commit()

    async def apply_accounts(self, *, item_id: str, accounts: list[dict[str, Any]], captured_at: datetime) -> None:
        async with self._session_factory() as session:
            for account in accounts:
                balances = account.get("balances") or {}
                values = {
                    "account_id": account["account_id"],
                    "item_id": item_id,
                    "name": account["name"],
                    "official_name": account.get("official_name"),
                    "mask": account.get("mask"),
                    "type": account["type"],
                    "subtype": account.get("subtype"),
                    "iso_currency_code": balances.get("iso_currency_code"),
                    "raw_json": account,
                    "updated_at": captured_at,
                }
                stmt = pg_insert(_AccountRow).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["account_id"], set_={k: v for k, v in values.items() if k != "account_id"}
                )
                await session.execute(stmt)
                session.add(
                    _BalanceSnapshotRow(
                        account_id=account["account_id"],
                        item_id=item_id,
                        captured_at=captured_at,
                        available=balances.get("available"),
                        current=balances.get("current"),
                        limit=balances.get("limit"),
                        iso_currency_code=balances.get("iso_currency_code"),
                    )
                )
            await session.commit()

    async def reconcile_transactions(
        self,
        *,
        item_id: str,
        start_date: date,
        end_date: date,
        transactions: list[dict[str, Any]],
        captured_at: datetime,
    ) -> None:
        seen = {txn["transaction_id"] for txn in transactions}
        async with self._session_factory() as session:
            for txn in transactions:
                pfc = txn.get("personal_finance_category") or {}
                values = {
                    "transaction_id": txn["transaction_id"],
                    "account_id": txn["account_id"],
                    "item_id": item_id,
                    "date": date.fromisoformat(txn["date"]) if isinstance(txn["date"], str) else txn["date"],
                    "amount": txn["amount"],
                    "iso_currency_code": txn.get("iso_currency_code"),
                    "name": txn["name"],
                    "merchant_name": txn.get("merchant_name"),
                    "pending": txn["pending"],
                    "pending_transaction_id": txn.get("pending_transaction_id"),
                    "pfc_primary": pfc.get("primary"),
                    "pfc_detailed": pfc.get("detailed"),
                    "removed": False,
                    "removed_at": None,
                    "raw_json": txn,
                    "updated_at": captured_at,
                }
                stmt = pg_insert(_TransactionRow).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["transaction_id"], set_={k: v for k, v in values.items() if k != "transaction_id"}
                )
                await session.execute(stmt)

            existing = (
                await session.execute(
                    select(_TransactionRow).where(
                        _TransactionRow.item_id == item_id,
                        _TransactionRow.date >= start_date,
                        _TransactionRow.date <= end_date,
                        _TransactionRow.removed.is_(False),
                    )
                )
            ).scalars()
            for row in existing:
                if row.transaction_id not in seen:
                    row.removed = True
                    row.removed_at = captured_at
                    row.updated_at = captured_at
            link = await session.get(_LinkRow, item_id)
            if link is not None:
                link.last_synced_at = captured_at
                link.updated_at = captured_at
            await session.commit()

    async def apply_holdings(
        self, *, item_id: str, securities: list[dict[str, Any]], holdings: list[dict[str, Any]], captured_at: datetime
    ) -> None:
        async with self._session_factory() as session:
            for security in securities:
                values = {
                    "security_id": security["security_id"],
                    "name": security.get("name"),
                    "ticker_symbol": security.get("ticker_symbol"),
                    "type": security.get("type"),
                    "iso_currency_code": security.get("iso_currency_code"),
                    "raw_json": security,
                    "updated_at": captured_at,
                }
                stmt = pg_insert(_SecurityRow).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["security_id"], set_={k: v for k, v in values.items() if k != "security_id"}
                )
                await session.execute(stmt)
            for holding in holdings:
                session.add(
                    _HoldingSnapshotRow(
                        account_id=holding["account_id"],
                        security_id=holding["security_id"],
                        item_id=item_id,
                        captured_at=captured_at,
                        quantity=holding.get("quantity"),
                        cost_basis=holding.get("cost_basis"),
                        institution_price=holding.get("institution_price"),
                        institution_value=holding.get("institution_value"),
                        iso_currency_code=holding.get("iso_currency_code"),
                        raw_json=holding,
                    )
                )
            await session.commit()

    async def upsert_investment_transactions(
        self, *, item_id: str, transactions: list[dict[str, Any]], captured_at: datetime
    ) -> None:
        async with self._session_factory() as session:
            for txn in transactions:
                txn_date = txn["date"]
                values = {
                    "investment_transaction_id": txn["investment_transaction_id"],
                    "account_id": txn["account_id"],
                    "security_id": txn.get("security_id"),
                    "item_id": item_id,
                    "date": date.fromisoformat(txn_date) if isinstance(txn_date, str) else txn_date,
                    "amount": txn.get("amount"),
                    "quantity": txn.get("quantity"),
                    "price": txn.get("price"),
                    "fees": txn.get("fees"),
                    "type": txn.get("type"),
                    "subtype": txn.get("subtype"),
                    "iso_currency_code": txn.get("iso_currency_code"),
                    "removed": False,
                    "removed_at": None,
                    "raw_json": txn,
                    "updated_at": captured_at,
                }
                stmt = pg_insert(_InvestmentTransactionRow).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["investment_transaction_id"],
                    set_={k: v for k, v in values.items() if k != "investment_transaction_id"},
                )
                await session.execute(stmt)
            await session.commit()

    async def append_liability_snapshots(
        self, *, item_id: str, liabilities: dict[str, list[dict[str, Any]] | None], captured_at: datetime
    ) -> None:
        row_by_type = {
            "credit": _LiabilityCreditSnapshotRow,
            "mortgage": _LiabilityMortgageSnapshotRow,
            "student": _LiabilityStudentSnapshotRow,
        }
        async with self._session_factory() as session:
            for key, row_type in row_by_type.items():
                for entry in liabilities.get(key) or []:
                    session.add(
                        row_type(
                            account_id=entry["account_id"], item_id=item_id, captured_at=captured_at, raw_json=entry
                        )
                    )
            await session.commit()


def _stored_link(row: _LinkRow) -> StoredLink:
    return StoredLink(
        item_id=row.item_id,
        label=row.label,
        institution_id=row.institution_id,
        institution_name=row.institution_name,
        link_profile=LinkProfile(row.link_profile),
        products_requested=list(row.products_requested),
        products_authorized=list(row.products_authorized),
        products_billed=list(row.products_billed),
        status=row.status,
        access_token_secret=row.access_token_secret,
        last_synced_at=row.last_synced_at,
    )


def _merge_products(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for product in group:
            if product not in merged:
                merged.append(product)
    return merged
