"""Monthly per-bucket aggregation + lumpy-spend detection.

Pure gross totals: every bucket's monthly amount is the sum of its classified
transactions in that month, in Plaid's sign convention (+ outflow, - inflow). No
netting across buckets; the UI groups related buckets via `BucketDef.family` and shows
both sides separately so the user can read inflows and outflows honestly rather than
chasing a single net number whose timing is wrong for some providers.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from augur.budget.categorize import Classified
from augur.budget.schema import BucketDef, BucketKind, BudgetConfig
from augur.dates import DAYS_PER_MONTH


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(month: date, delta: int) -> date:
    total = month.year * 12 + (month.month - 1) + delta
    return date(total // 12, total % 12 + 1, 1)


@dataclass(frozen=True)
class MonthlyBucketSeries:
    """Per-month signed total in one bucket, ordered earliest-first.

    Values use Plaid's sign convention (+ = money out, - = money in)."""

    bucket_id: str
    months: tuple[date, ...]
    amounts: tuple[float, ...]


@dataclass(frozen=True)
class LumpyTransaction:
    transaction_id: str
    date: date
    amount: float
    name: str
    merchant_name: str | None
    bucket_id: str


@dataclass(frozen=True)
class BucketReport:
    bucket: BucketDef
    monthly: MonthlyBucketSeries
    window_monthly_avg: float
    transaction_count: int


@dataclass(frozen=True)
class AggregateReport:
    months: tuple[date, ...]
    buckets: tuple[BucketReport, ...]
    lumpy: tuple[LumpyTransaction, ...]


def _enumerate_months(start: date, end: date) -> tuple[date, ...]:
    """Inclusive list of month-start dates covering [start, end]."""
    months: list[date] = []
    cursor = _month_start(start)
    last = _month_start(end)
    while cursor <= last:
        months.append(cursor)
        cursor = _add_months(cursor, 1)
    return tuple(months)


def _gross_monthly_totals(
    classified: Iterable[Classified], *, months: tuple[date, ...]
) -> dict[str, dict[date, float]]:
    by_bucket: dict[str, dict[date, float]] = defaultdict(lambda: dict.fromkeys(months, 0.0))
    months_set = set(months)
    for entry in classified:
        month = _month_start(entry.transaction.date)
        if month in months_set:
            by_bucket[entry.bucket_id][month] += entry.transaction.amount
    return by_bucket


def aggregate(
    classified: tuple[Classified, ...], *, config: BudgetConfig, window_start: date, window_end: date
) -> AggregateReport:
    """Per-bucket monthly view + a list of lumpy single transactions over [window_start, window_end].

    `window_start` / `window_end` are the actual covered dates (inclusive) -- not month
    boundaries -- so they bound the day count that normalizes per-month averages. The monthly
    series itself still snaps to calendar months for the trend chart.
    """
    months = _enumerate_months(window_start, window_end)
    months_set = set(months)
    gross = _gross_monthly_totals(classified, months=months)
    bucket_by_id = {bucket.id: bucket for bucket in config.buckets}

    # Day-normalized monthly average: signed window total / days actually covered, scaled to a
    # representative month. Counting days (not calendar-month slots) is what keeps a partial
    # current month -- or a mid-month coverage start -- from being treated as a full month, which
    # otherwise biases every average toward zero by up to a month's worth.
    days_covered = max((window_end - window_start).days + 1, 1)
    counts_by_bucket: dict[str, int] = defaultdict(int)
    for entry in classified:
        if _month_start(entry.transaction.date) in months_set:
            counts_by_bucket[entry.bucket_id] += 1

    bucket_reports: list[BucketReport] = []
    for bucket in config.buckets:
        series_map = gross.get(bucket.id, dict.fromkeys(months, 0.0))
        amounts = tuple(series_map[month] for month in months)
        window_monthly_avg = sum(amounts) / days_covered * DAYS_PER_MONTH
        bucket_reports.append(
            BucketReport(
                bucket=bucket,
                monthly=MonthlyBucketSeries(bucket_id=bucket.id, months=months, amounts=amounts),
                window_monthly_avg=window_monthly_avg,
                transaction_count=counts_by_bucket.get(bucket.id, 0),
            )
        )

    # Lumpy = a single large debit, regardless of bucket. Inflow / transfer / income
    # buckets are excluded so reimbursement deposits + tax payments don't dominate the
    # list -- the goal is "single big outflows the user might want to reclassify."
    lumpy_threshold = config.lumpy_threshold_usd
    lumpy = tuple(
        sorted(
            (
                LumpyTransaction(
                    transaction_id=entry.transaction.transaction_id,
                    date=entry.transaction.date,
                    amount=entry.transaction.amount,
                    name=entry.transaction.name,
                    merchant_name=entry.transaction.merchant_name,
                    bucket_id=entry.bucket_id,
                )
                for entry in classified
                if entry.transaction.amount >= lumpy_threshold
                and _month_start(entry.transaction.date) in months_set
                and bucket_by_id[entry.bucket_id].kind == BucketKind.EXPENSE
            ),
            key=lambda item: item.amount,
            reverse=True,
        )
    )

    return AggregateReport(months=months, buckets=tuple(bucket_reports), lumpy=lumpy)


__all__ = ["AggregateReport", "BucketReport", "LumpyTransaction", "MonthlyBucketSeries", "aggregate"]
