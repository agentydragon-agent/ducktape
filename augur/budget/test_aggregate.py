"""Budget aggregation tests, focused on day-normalized monthly averages over partial months."""

from __future__ import annotations

from datetime import date

import pytest
import pytest_bazel
from more_itertools import one

from augur.budget.aggregate import aggregate
from augur.budget.categorize import Classified
from augur.budget.schema import BucketDef, BucketKind, BudgetConfig, BudgetSourceConfig, TransferDirection
from augur.dates import DAYS_PER_MONTH
from plaid_utils.schema import TransactionRow


def _tx(transaction_id: str, on: date, amount: float) -> TransactionRow:
    return TransactionRow(
        transaction_id=transaction_id,
        account_id="acct",
        item_id="item",
        date=on,
        amount=amount,
        name=transaction_id,
        merchant_name=None,
        pending=False,
        pfc_primary=None,
        pfc_detailed=None,
        raw_json={},
    )


def _single_bucket_config() -> BudgetConfig:
    return BudgetConfig(
        source=BudgetSourceConfig(),
        buckets=(
            BucketDef(id="groceries", label="Groceries", kind=BucketKind.EXPENSE, direction=TransferDirection.OUTFLOW),
            BucketDef(id="refunds", label="Refunds", kind=BucketKind.INFLOW, direction=TransferDirection.INFLOW),
        ),
        default_outflow_bucket_id="groceries",
        default_inflow_bucket_id="refunds",
        include_default_rules=False,
    )


def test_partial_current_month_not_counted_as_whole() -> None:
    # Two full months at $3000 and an empty partial June (window ends June 2). The run rate is
    # ~$3000/mo; dividing the $6000 window total by 3 calendar-month slots gave a bogus $2000/mo.
    config = _single_bucket_config()
    classified = (
        Classified(transaction=_tx("a", date(2026, 4, 15), 3000.0), bucket_id="groceries"),
        Classified(transaction=_tx("b", date(2026, 5, 15), 3000.0), bucket_id="groceries"),
    )
    report = aggregate(classified, config=config, window_start=date(2026, 4, 1), window_end=date(2026, 6, 2))

    bucket_report = one(b for b in report.buckets if b.bucket.id == "groceries")
    days = (date(2026, 6, 2) - date(2026, 4, 1)).days + 1
    assert bucket_report.window_monthly_avg == pytest.approx(6000.0 / days * DAYS_PER_MONTH)
    # Close to the true ~$3000/mo run rate, and far above the old sum/3 == $2000.
    assert bucket_report.window_monthly_avg == pytest.approx(3000.0, rel=0.05)
    # The trend series still snaps to calendar-month columns including the partial month.
    assert report.months == (date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1))


def test_mid_month_coverage_start_not_counted_as_whole() -> None:
    # Coverage begins mid-month (Mar 15). Only the 17 covered days of March should weigh in, not
    # a full March -- so $1000 over a half-month reads as a high monthly rate, not $1000/2 months.
    config = _single_bucket_config()
    classified = (Classified(transaction=_tx("a", date(2026, 3, 20), 1000.0), bucket_id="groceries"),)
    report = aggregate(classified, config=config, window_start=date(2026, 3, 15), window_end=date(2026, 4, 30))

    bucket_report = one(b for b in report.buckets if b.bucket.id == "groceries")
    days = (date(2026, 4, 30) - date(2026, 3, 15)).days + 1
    assert bucket_report.window_monthly_avg == pytest.approx(1000.0 / days * DAYS_PER_MONTH)


def test_inflow_average_keeps_sign() -> None:
    # Plaid signs inflows negative; the day-normalized average must stay signed so the UI can
    # tell expense-side from income-side buckets.
    config = _single_bucket_config()
    classified = (Classified(transaction=_tx("r", date(2026, 1, 10), -500.0), bucket_id="groceries"),)
    report = aggregate(classified, config=config, window_start=date(2026, 1, 1), window_end=date(2026, 1, 31))

    bucket_report = one(b for b in report.buckets if b.bucket.id == "groceries")
    assert bucket_report.window_monthly_avg < 0


if __name__ == "__main__":
    pytest_bazel.main()
