"""Read-only portfolio projections over the synced Plaid mirror database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, func, select

from plaid_utils.schema import (
    AccountRow,
    BalanceSnapshotRow,
    HoldingSnapshotRow,
    LinkRow,
    SecurityRow,
    async_session_factory,
)


@dataclass(frozen=True)
class CurrentCashBalance:
    account_id: str
    account_name: str
    institution_name: str | None
    captured_at: datetime
    available: float | None
    current: float | None
    iso_currency_code: str | None


@dataclass(frozen=True)
class CurrentHolding:
    account_id: str
    account_name: str
    institution_name: str | None
    security_id: str
    security_name: str | None
    ticker_symbol: str | None
    security_type: str | None
    captured_at: datetime
    quantity: float | None
    cost_basis: float | None
    institution_price: float | None
    institution_value: float | None
    iso_currency_code: str | None


async def read_current_cash_balances(
    *, db_url: str, account_ids: tuple[str, ...], iso_currency_code: str = "USD"
) -> tuple[CurrentCashBalance, ...]:
    if not account_ids:
        return ()
    engine, session_factory = async_session_factory(db_url)
    try:
        ranked = (
            select(
                BalanceSnapshotRow.id.label("balance_snapshot_id"),
                func.row_number()
                .over(
                    partition_by=BalanceSnapshotRow.account_id,
                    order_by=(desc(BalanceSnapshotRow.captured_at), desc(BalanceSnapshotRow.id)),
                )
                .label("row_number"),
            )
            .join(AccountRow, AccountRow.account_id == BalanceSnapshotRow.account_id)
            .join(LinkRow, LinkRow.item_id == BalanceSnapshotRow.item_id)
            .where(BalanceSnapshotRow.account_id.in_(account_ids), LinkRow.status != "revoked")
            .subquery()
        )
        stmt = (
            select(BalanceSnapshotRow, AccountRow, LinkRow)
            .join(ranked, ranked.c.balance_snapshot_id == BalanceSnapshotRow.id)
            .join(AccountRow, AccountRow.account_id == BalanceSnapshotRow.account_id)
            .join(LinkRow, LinkRow.item_id == BalanceSnapshotRow.item_id)
            .where(ranked.c.row_number == 1)
            .order_by(BalanceSnapshotRow.account_id)
        )
        async with session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return tuple(
            CurrentCashBalance(
                account_id=balance.account_id,
                account_name=account.name,
                institution_name=link.institution_name,
                captured_at=balance.captured_at,
                available=balance.available,
                current=balance.current,
                iso_currency_code=balance.iso_currency_code,
            )
            for balance, account, link in rows
            if balance.iso_currency_code in (None, iso_currency_code)
        )
    finally:
        await engine.dispose()


async def read_current_holdings(
    *, db_url: str, account_ids: tuple[str, ...], iso_currency_code: str = "USD"
) -> tuple[CurrentHolding, ...]:
    if not account_ids:
        return ()
    engine, session_factory = async_session_factory(db_url)
    try:
        ranked = (
            select(
                HoldingSnapshotRow.id.label("holding_snapshot_id"),
                func.row_number()
                .over(
                    partition_by=(HoldingSnapshotRow.account_id, HoldingSnapshotRow.security_id),
                    order_by=(desc(HoldingSnapshotRow.captured_at), desc(HoldingSnapshotRow.id)),
                )
                .label("row_number"),
            )
            .join(AccountRow, AccountRow.account_id == HoldingSnapshotRow.account_id)
            .join(LinkRow, LinkRow.item_id == HoldingSnapshotRow.item_id)
            .join(SecurityRow, SecurityRow.security_id == HoldingSnapshotRow.security_id)
            .where(HoldingSnapshotRow.account_id.in_(account_ids), LinkRow.status != "revoked")
            .subquery()
        )
        stmt = (
            select(HoldingSnapshotRow, AccountRow, LinkRow, SecurityRow)
            .join(ranked, ranked.c.holding_snapshot_id == HoldingSnapshotRow.id)
            .join(AccountRow, AccountRow.account_id == HoldingSnapshotRow.account_id)
            .join(LinkRow, LinkRow.item_id == HoldingSnapshotRow.item_id)
            .join(SecurityRow, SecurityRow.security_id == HoldingSnapshotRow.security_id)
            .where(ranked.c.row_number == 1)
            .order_by(HoldingSnapshotRow.account_id, HoldingSnapshotRow.security_id)
        )
        async with session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return tuple(
            CurrentHolding(
                account_id=holding.account_id,
                account_name=account.name,
                institution_name=link.institution_name,
                security_id=holding.security_id,
                security_name=security.name,
                ticker_symbol=security.ticker_symbol,
                security_type=security.type,
                captured_at=holding.captured_at,
                quantity=holding.quantity,
                cost_basis=holding.cost_basis,
                institution_price=holding.institution_price,
                institution_value=holding.institution_value,
                iso_currency_code=holding.iso_currency_code,
            )
            for holding, account, link, security in rows
            if holding.iso_currency_code in (None, iso_currency_code)
        )
    finally:
        await engine.dispose()
