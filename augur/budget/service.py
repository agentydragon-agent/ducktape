"""Budget snapshot service: loads transactions, classifies, aggregates, returns wire types.

The service holds the plaid mirror session factory (constructed once at server startup,
shared across requests) so every endpoint reuses the same asyncpg connection pool. SSL
handshake + pool init cost ~500ms over the cluster port-forward; doing it per request
was the dominant latency in the early budget endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from augur.budget.aggregate import aggregate
from augur.budget.categorize import classify
from augur.budget.schema import BudgetConfig
from augur.budget.wire import (
    BucketMonthly,
    BucketView,
    BudgetSnapshotResponse,
    BudgetTransactionsResponse,
    LumpyView,
    TrailingMonthsWindow,
    TransactionView,
    WindowSpec,
)
from plaid_utils.read_model import read_account_directory, read_transactions


def _resolve_window(window: WindowSpec, *, today: date, coverage_starts: date | None) -> date:
    """Map a wire `WindowSpec` to the window's start (the actual first covered day).

    For `TrailingMonthsWindow`, walks back N calendar months from the month containing `today`.
    For `CoverageWindow`, anchors at `coverage_starts` (raises if the deployment has none).
    In either case, the start is clamped to `coverage_starts` -- months before that are partial
    cross-account coverage and would skew family totals. The window always ends at `today`.
    """
    current_month = date(today.year, today.month, 1)
    if isinstance(window, TrailingMonthsWindow):
        total = current_month.year * 12 + (current_month.month - 1) - (window.months - 1)
        start_month = date(total // 12, total % 12 + 1, 1)
    else:
        if coverage_starts is None:
            raise ValueError(
                "since_coverage_start window requested but no coverage_starts is configured "
                "for this deployment; either configure BudgetSourceConfig.coverage_starts or "
                "pick a trailing-months window"
            )
        start_month = date(coverage_starts.year, coverage_starts.month, 1)
    if coverage_starts is not None and start_month < coverage_starts:
        start_month = coverage_starts
    return start_month


@dataclass(frozen=True)
class BudgetService:
    config: BudgetConfig
    session_factory: async_sessionmaker[AsyncSession]

    async def build_snapshot(self, *, window: WindowSpec) -> BudgetSnapshotResponse:
        """Pull + categorize + aggregate, packaged as the wire snapshot."""
        today = date.today()
        coverage_starts = self.config.source.coverage_starts
        start_month = _resolve_window(window, today=today, coverage_starts=coverage_starts)
        transactions = await read_transactions(
            session_factory=self.session_factory,
            start_date=start_month,
            end_date=today,
            account_ids=self.config.source.plaid_account_ids,
        )
        classified = classify(transactions, config=self.config)
        report = aggregate(classified, config=self.config, window_start=start_month, window_end=today)
        return BudgetSnapshotResponse(
            months=report.months,
            buckets=tuple(
                BucketView(id=bucket.id, label=bucket.label, kind=bucket.kind, family=bucket.family)
                for bucket in self.config.buckets
            ),
            monthly_by_bucket=tuple(
                BucketMonthly(
                    bucket_id=bucket_report.bucket.id,
                    monthly_amounts=bucket_report.monthly.amounts,
                    window_monthly_avg=bucket_report.window_monthly_avg,
                    transaction_count=bucket_report.transaction_count,
                )
                for bucket_report in report.buckets
            ),
            lumpy=tuple(
                LumpyView(
                    transaction_id=item.transaction_id,
                    date=item.date,
                    amount=item.amount,
                    name=item.name,
                    merchant_name=item.merchant_name,
                    bucket_id=item.bucket_id,
                )
                for item in report.lumpy
            ),
            lumpy_threshold_usd=self.config.lumpy_threshold_usd,
            data_window_start=start_month,
            data_window_end=today,
            coverage_starts=coverage_starts,
        )

    async def list_transactions_in_bucket(self, *, bucket_id: str, window: WindowSpec) -> BudgetTransactionsResponse:
        """Drill-down: all transactions in one bucket, enriched with account+link names."""
        today = date.today()
        coverage_starts = self.config.source.coverage_starts
        start_month = _resolve_window(window, today=today, coverage_starts=coverage_starts)
        transactions = await read_transactions(
            session_factory=self.session_factory,
            start_date=start_month,
            end_date=today,
            account_ids=self.config.source.plaid_account_ids,
        )
        accounts, links = await read_account_directory(
            session_factory=self.session_factory, account_ids=self.config.source.plaid_account_ids
        )
        classified = classify(transactions, config=self.config)
        bucket_ids = {bucket.id for bucket in self.config.buckets}
        if bucket_id not in bucket_ids:
            raise ValueError(f"unknown bucket_id {bucket_id!r}; have {sorted(bucket_ids)}")
        return BudgetTransactionsResponse(
            bucket_id=bucket_id,
            transactions=tuple(
                TransactionView(
                    transaction_id=entry.transaction.transaction_id,
                    date=entry.transaction.date,
                    amount=entry.transaction.amount,
                    name=entry.transaction.name,
                    merchant_name=entry.transaction.merchant_name,
                    pfc_primary=entry.transaction.pfc_primary,
                    pfc_detailed=entry.transaction.pfc_detailed,
                    account_name=accounts[entry.transaction.account_id].name,
                    institution_name=links[entry.transaction.item_id].institution_name,
                    bucket_id=entry.bucket_id,
                )
                for entry in classified
                if entry.bucket_id == bucket_id
            ),
        )
