"""Monthly per-bucket aggregation with reimbursement netting and lumpy-spend detection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from augur.budget.categorize import Classified
from augur.budget.schema import BucketDef, BucketKind, BudgetConfig


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _add_months(month: date, delta: int) -> date:
    total = month.year * 12 + (month.month - 1) + delta
    return date(total // 12, total % 12 + 1, 1)


@dataclass(frozen=True)
class MonthlyBucketSeries:
    """Per-month signed total in one bucket, ordered earliest-first.

    Values use Plaid's sign convention (+ = money out, - = money in). Net-of-reimbursement
    rows (kind=REIMBURSABLE with `reimbursed_by` set) carry charges minus reimbursements
    over a rolling window."""

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
    current_monthly_avg: float
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
    for entry in classified:
        month = _month_start(entry.transaction.date)
        if month in by_bucket[entry.bucket_id]:
            by_bucket[entry.bucket_id][month] += entry.transaction.amount
    return by_bucket


def _rolling_window_sum(amounts: dict[date, float], window_months: int) -> dict[date, float]:
    """For each month m, sum amounts over [m - (window-1) ... m]. Used for reimbursement netting."""
    ordered = sorted(amounts)
    cumulative: dict[date, float] = {}
    queue: list[date] = []
    rolling = 0.0
    for month in ordered:
        queue.append(month)
        rolling += amounts[month]
        if len(queue) > window_months:
            rolling -= amounts[queue.pop(0)]
        cumulative[month] = rolling
    return cumulative


def aggregate(
    classified: tuple[Classified, ...], *, config: BudgetConfig, start_month: date, end_month: date
) -> AggregateReport:
    """Build the per-bucket monthly view + lumpy list over the requested month window."""
    months = _enumerate_months(start_month, end_month)
    gross = _gross_monthly_totals(classified, months=months)
    bucket_by_id = {bucket.id: bucket for bucket in config.buckets}

    # For each REIMBURSABLE bucket, replace its raw charges with a rolling-window NET (charges
    # minus its share of paired reimbursements). When multiple reimbursable buckets share the
    # same reimbursement stream (e.g. esketamine + therapy both paired with `medical_reimbursement`),
    # the rolling reimbursement total is allocated to each bucket in proportion to the bucket's
    # window gross. Anthem-style ACH deposits don't carry a tag back to the originating claim,
    # so proportional-by-gross is the best available split.
    reimbursables_by_payer: dict[str, list[str]] = defaultdict(list)
    for bucket in config.buckets:
        if bucket.kind == BucketKind.REIMBURSABLE and bucket.reimbursed_by:
            reimbursables_by_payer[bucket.reimbursed_by].append(bucket.id)
    window_months = config.reimbursement_window_months
    rolling_gross: dict[str, dict[date, float]] = {
        bucket.id: _rolling_window_sum(gross.get(bucket.id, dict.fromkeys(months, 0.0)), window_months)
        for bucket in config.buckets
    }
    netted: dict[str, dict[date, float]] = {}
    for bucket in config.buckets:
        if bucket.kind == BucketKind.REIMBURSABLE and bucket.reimbursed_by:
            peers = reimbursables_by_payer[bucket.reimbursed_by]
            charges_window = rolling_gross[bucket.id]
            refund_window = rolling_gross[bucket.reimbursed_by]
            netted_series: dict[date, float] = {}
            for month in months:
                total_peer_charges = sum(rolling_gross[peer_id][month] for peer_id in peers)
                share = (charges_window[month] / total_peer_charges) if total_peer_charges > 0 else 0.0
                # refund_window entries are negative (Plaid sign); adding moves the net toward zero.
                allocated_refund = refund_window[month] * share
                netted_series[month] = (charges_window[month] + allocated_refund) / window_months
            netted[bucket.id] = netted_series
        else:
            netted[bucket.id] = gross.get(bucket.id, dict.fromkeys(months, 0.0))

    # Recent monthly average uses the last 3 months of the visible window (or fewer if the
    # window is shorter). Reimbursable buckets read from the netted series; everything else
    # from gross.
    recent_window = months[-3:] if len(months) >= 3 else months
    bucket_reports: list[BucketReport] = []
    counts_by_bucket: dict[str, int] = defaultdict(int)
    for entry in classified:
        if _month_start(entry.transaction.date) in set(months):
            counts_by_bucket[entry.bucket_id] += 1
    for bucket in config.buckets:
        series_map = netted[bucket.id]
        amounts = tuple(series_map[month] for month in months)
        recent = [series_map[month] for month in recent_window]
        avg = sum(recent) / len(recent) if recent else 0.0
        bucket_reports.append(
            BucketReport(
                bucket=bucket,
                monthly=MonthlyBucketSeries(bucket_id=bucket.id, months=months, amounts=amounts),
                current_monthly_avg=avg,
                transaction_count=counts_by_bucket.get(bucket.id, 0),
            )
        )

    lumpy_threshold = config.lumpy_threshold_usd
    lumpy = tuple(
        LumpyTransaction(
            transaction_id=entry.transaction.transaction_id,
            date=entry.transaction.date,
            amount=entry.transaction.amount,
            name=entry.transaction.name,
            merchant_name=entry.transaction.merchant_name,
            bucket_id=entry.bucket_id,
        )
        for entry in classified
        # Lumpy = a single large debit, regardless of bucket. Reimbursement deposits are large
        # too but they're inflows (negative amount); excluding inflows keeps the list to actual
        # one-off purchases the user might reclassify.
        if entry.transaction.amount >= lumpy_threshold
        and _month_start(entry.transaction.date) in set(months)
        and bucket_by_id[entry.bucket_id].kind not in (BucketKind.TRANSFER, BucketKind.REIMBURSEMENT)
    )
    # Largest first -- that's what the user wants to eyeball.
    lumpy = tuple(sorted(lumpy, key=lambda item: item.amount, reverse=True))

    return AggregateReport(months=months, buckets=tuple(bucket_reports), lumpy=lumpy)
